"""
PgGraphQueryService — graph_query_service.py의 Neo4j 전환.

주요 기능:
  - check_graph_data_exists → analyzer_tables 카운트
  - fetch_graph_data → 전체 테이블/컬럼/관계 조회
  - fetch_related_tables → FK + 프로시저 참조 테이블 조회
  - cleanup / delete → TRUNCATE / DELETE
"""

import logging
from typing import Any, Dict, List

import asyncpg

logger = logging.getLogger(__name__)

_VECTOR_EXCLUDE_KEYS = {"embedding", "vector"}


def _sanitize_props(props: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v for k, v in props.items()
        if k not in _VECTOR_EXCLUDE_KEYS
        and not (isinstance(v, (list, tuple)) and len(v) >= 128)
    }


class PgGraphQueryService:
    """PostgreSQL 기반 그래프 데이터 조회/삭제 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def check_graph_data_exists(self) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            cnt = await conn.fetchval("SELECT count(*) FROM analyzer_tables") or 0
            return {"hasData": cnt > 0, "nodeCount": cnt}

    async def fetch_graph_data(self) -> Dict[str, Any]:
        nodes: List[Dict] = []
        relationships: List[Dict] = []

        async with self._pool.acquire() as conn:
            tables = await conn.fetch(
                """SELECT id, db, schema_name, name, description, description_source,
                          analyzed_description, table_type, datasource
                   FROM analyzer_tables"""
            )
            for t in tables:
                props = _sanitize_props(dict(t))
                props.pop("id", None)
                nodes.append({
                    "Node ID": str(t["id"]),
                    "Labels": ["Analyzer_Table"],
                    "Properties": props,
                })

            columns = await conn.fetch(
                """SELECT c.id, c.fqn, c.name, c.dtype, c.description, c.description_source,
                          c.nullable, c.is_primary_key, c.table_id
                   FROM analyzer_columns c"""
            )
            for c in columns:
                props = _sanitize_props(dict(c))
                table_id = props.pop("table_id", None)
                cid = props.pop("id", None)
                nodes.append({
                    "Node ID": f"col:{cid}",
                    "Labels": ["Analyzer_Column"],
                    "Properties": props,
                })
                if table_id:
                    relationships.append({
                        "Relationship ID": f"hc:{table_id}:{cid}",
                        "Type": "HAS_COLUMN",
                        "Start Node ID": str(table_id),
                        "End Node ID": f"col:{cid}",
                        "Properties": {},
                    })

            rels = await conn.fetch(
                """SELECT r.id, r.from_table_id, r.to_table_id, r.rel_type,
                          r.source_column, r.target_column, r.source
                   FROM analyzer_table_relationships r"""
            )
            for r in rels:
                relationships.append({
                    "Relationship ID": f"rel:{r['id']}",
                    "Type": r["rel_type"],
                    "Start Node ID": str(r["from_table_id"]),
                    "End Node ID": str(r["to_table_id"]),
                    "Properties": {
                        "sourceColumn": r["source_column"],
                        "targetColumn": r["target_column"],
                        "source": r["source"],
                    },
                })

        return {"Nodes": nodes, "Relationships": relationships}

    async def fetch_related_tables(self, table_name: str) -> Dict[str, Any]:
        tables: List[Dict] = []
        rels: List[Dict] = []
        seen_tables = {table_name}
        seen_rels = set()

        async with self._pool.acquire() as conn:
            fk_rows = await conn.fetch(
                """SELECT t1.name AS from_table, t1.schema_name AS from_schema, t1.description AS from_desc,
                          t2.name AS to_table, t2.schema_name AS to_schema, t2.description AS to_desc,
                          r.source_column, r.target_column, r.source
                   FROM analyzer_table_relationships r
                   JOIN analyzer_tables t1 ON t1.id = r.from_table_id
                   JOIN analyzer_tables t2 ON t2.id = r.to_table_id
                   WHERE (t1.name = $1 OR t2.name = $1)
                     AND r.rel_type = 'FK_TO_TABLE'""",
                table_name,
            )

            fk_by_pair: Dict[tuple, Dict] = {}
            for row in fk_rows:
                ft, tt = row["from_table"], row["to_table"]
                for name, schema, desc in [(ft, row["from_schema"], row["from_desc"]),
                                            (tt, row["to_schema"], row["to_desc"])]:
                    if name and name not in seen_tables:
                        seen_tables.add(name)
                        tables.append({"name": name, "schema": schema or "public", "description": desc})

                pair = (ft, tt)
                if pair not in fk_by_pair:
                    fk_by_pair[pair] = {"source": row["source"], "column_pairs": []}
                if row["source_column"] or row["target_column"]:
                    fk_by_pair[pair]["column_pairs"].append({
                        "source": row["source_column"],
                        "target": row["target_column"],
                    })

            for (ft, tt), data in fk_by_pair.items():
                rk = f"{ft}->{tt}"
                if rk not in seen_rels:
                    seen_rels.add(rk)
                    rels.append({
                        "from_table": ft,
                        "to_table": tt,
                        "type": "FK_TO_TABLE",
                        "source": data["source"],
                        "column_pairs": data["column_pairs"],
                    })

            proc_rows = await conn.fetch(
                """SELECT DISTINCT t2.name, t2.schema_name, t2.description
                   FROM analyzer_ast_table_refs ref1
                   JOIN analyzer_tables t1 ON t1.id = ref1.table_id AND t1.name = $1
                   JOIN analyzer_ast_nodes n1 ON n1.id = ref1.ast_node_id
                   JOIN analyzer_ast_nodes proc ON proc.id = n1.parent_id
                   JOIN analyzer_ast_table_refs ref2 ON ref2.ast_node_id IN (
                       SELECT id FROM analyzer_ast_nodes WHERE parent_id = proc.id
                   )
                   JOIN analyzer_tables t2 ON t2.id = ref2.table_id AND t2.name <> $1""",
                table_name,
            )
            for pr in proc_rows:
                if pr["name"] not in seen_tables:
                    seen_tables.add(pr["name"])
                    tables.append({"name": pr["name"], "schema": pr["schema_name"] or "public", "description": pr["description"]})
                    rk = f"{table_name}->{pr['name']}"
                    if rk not in seen_rels:
                        seen_rels.add(rk)
                        rels.append({
                            "from_table": table_name,
                            "to_table": pr["name"],
                            "type": "CO_REFERENCED",
                            "source": "procedure",
                            "column_pairs": [],
                        })

        return {"base_table": table_name, "tables": tables, "relationships": rels}

    async def cleanup_graph(self, keep_datasource: bool = True) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM analyzer_ast_edges")
                await conn.execute("DELETE FROM analyzer_ast_table_refs")
                await conn.execute("DELETE FROM analyzer_etl_table_refs")
                await conn.execute("DELETE FROM analyzer_user_stories")
                await conn.execute("DELETE FROM analyzer_ast_nodes")
                await conn.execute("DELETE FROM analyzer_column_relationships")
                await conn.execute("DELETE FROM analyzer_table_relationships")
                await conn.execute("DELETE FROM analyzer_columns")
                await conn.execute("DELETE FROM analyzer_tables")
                await conn.execute("DELETE FROM analyzer_lineage_edges")
                await conn.execute("DELETE FROM analyzer_lineage_nodes")
                await conn.execute("DELETE FROM analyzer_schema_datasource")
                await conn.execute("DELETE FROM analyzer_schemas")
                if not keep_datasource:
                    await conn.execute("DELETE FROM analyzer_data_sources")
        logger.info("Analyzer 그래프 데이터 삭제 완료")

    async def delete_graph_data(self, include_files: bool = False) -> Dict[str, str]:
        await self.cleanup_graph(keep_datasource=True)
        return {"message": "Analyzer 그래프 데이터가 삭제되었습니다."}
