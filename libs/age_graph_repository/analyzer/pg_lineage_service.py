"""
PgLineageService — data_lineage_service.py + lineage_analyzer의 Neo4j 전환.

ETLProcess, DataSource, DATA_FLOW_TO, TRANSFORMS_TO 관계를 PostgreSQL로 전환.
"""

import logging
from typing import Any, Dict, List

import asyncpg

logger = logging.getLogger(__name__)


class PgLineageService:
    """PostgreSQL 기반 리니지 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def fetch_lineage_graph(self) -> Dict[str, Any]:
        nodes: List[Dict] = []
        edges: List[Dict] = []

        async with self._pool.acquire() as conn:
            node_rows = await conn.fetch(
                """SELECT id, name, node_type, source_type, extra_props
                   FROM analyzer_lineage_nodes
                   ORDER BY node_type, name"""
            )
            for r in node_rows:
                nt = r["node_type"]
                extra = r["extra_props"]
                if isinstance(extra, str):
                    import json as _json
                    try:
                        extra = _json.loads(extra)
                    except Exception:
                        extra = {}
                elif extra is None:
                    extra = {}
                if nt == "DataSource":
                    nt = extra.get("type", r["source_type"] or "SOURCE")
                elif nt == "ETLProcess":
                    nt = "ETL"
                nodes.append({
                    "id": str(r["id"]),
                    "name": r["name"],
                    "type": nt,
                    "properties": extra,
                })

            edge_rows = await conn.fetch(
                """SELECT e.id, e.from_node_id, e.to_node_id, e.edge_type, e.extra_props
                   FROM analyzer_lineage_edges e"""
            )
            for e in edge_rows:
                e_extra = e["extra_props"]
                if isinstance(e_extra, str):
                    import json as _json2
                    try:
                        e_extra = _json2.loads(e_extra)
                    except Exception:
                        e_extra = {}
                elif e_extra is None:
                    e_extra = {}
                edges.append({
                    "id": str(e["id"]),
                    "source": str(e["from_node_id"]),
                    "target": str(e["to_node_id"]),
                    "type": e["edge_type"],
                    "properties": e_extra if isinstance(e_extra, dict) else {},
                })

            stats_row = await conn.fetchrow(
                """SELECT
                     sum(CASE WHEN node_type = 'ETLProcess' THEN 1 ELSE 0 END) AS etl_count,
                     sum(CASE WHEN node_type = 'DataSource' AND source_type = 'SOURCE' THEN 1 ELSE 0 END) AS source_count,
                     sum(CASE WHEN node_type = 'DataSource' AND source_type = 'TARGET' THEN 1 ELSE 0 END) AS target_count
                   FROM analyzer_lineage_nodes"""
            )

        stats = {}
        if stats_row:
            stats = {
                "etlCount": stats_row["etl_count"] or 0,
                "sourceCount": stats_row["source_count"] or 0,
                "targetCount": stats_row["target_count"] or 0,
                "flowCount": len(edges),
            }

        return {"nodes": nodes, "edges": edges, "stats": stats}

    async def save_lineage(
        self,
        proc_name: str,
        source_tables: List[str],
        target_tables: List[str],
        operation_type: str = "UNKNOWN",
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                etl_id = await conn.fetchval(
                    """INSERT INTO analyzer_lineage_nodes (name, node_type, extra_props)
                       VALUES ($1, 'ETLProcess', $2::jsonb)
                       ON CONFLICT (name, node_type) DO UPDATE SET extra_props = EXCLUDED.extra_props
                       RETURNING id""",
                    proc_name,
                    f'{{"operation_type": "{operation_type}"}}',
                )

                for src in source_tables:
                    src_id = await conn.fetchval(
                        """INSERT INTO analyzer_lineage_nodes (name, node_type, source_type)
                           VALUES ($1, 'DataSource', 'SOURCE')
                           ON CONFLICT (name, node_type) DO UPDATE SET source_type = 'SOURCE'
                           RETURNING id""",
                        src,
                    )
                    await conn.execute(
                        """INSERT INTO analyzer_lineage_edges (from_node_id, to_node_id, edge_type)
                           VALUES ($1, $2, 'DATA_FLOW_TO')
                           ON CONFLICT DO NOTHING""",
                        src_id, etl_id,
                    )

                for tgt in target_tables:
                    tgt_id = await conn.fetchval(
                        """INSERT INTO analyzer_lineage_nodes (name, node_type, source_type)
                           VALUES ($1, 'DataSource', 'TARGET')
                           ON CONFLICT (name, node_type) DO UPDATE SET source_type = 'TARGET'
                           RETURNING id""",
                        tgt,
                    )
                    await conn.execute(
                        """INSERT INTO analyzer_lineage_edges (from_node_id, to_node_id, edge_type)
                           VALUES ($1, $2, 'TRANSFORMS_TO')
                           ON CONFLICT DO NOTHING""",
                        etl_id, tgt_id,
                    )

                for src in source_tables:
                    for tgt in target_tables:
                        src_id = await conn.fetchval(
                            "SELECT id FROM analyzer_lineage_nodes WHERE name=$1 AND node_type='DataSource'", src
                        )
                        tgt_id = await conn.fetchval(
                            "SELECT id FROM analyzer_lineage_nodes WHERE name=$1 AND node_type='DataSource'", tgt
                        )
                        if src_id and tgt_id:
                            await conn.execute(
                                """INSERT INTO analyzer_lineage_edges (from_node_id, to_node_id, edge_type)
                                   VALUES ($1, $2, 'DATA_FLOW_TO')
                                   ON CONFLICT DO NOTHING""",
                                src_id, tgt_id,
                            )

    async def save_etl_table_refs(
        self, ast_node_id: int, table_name: str, ref_type: str = "ETL_READS"
    ) -> None:
        async with self._pool.acquire() as conn:
            table_id = await conn.fetchval(
                "SELECT id FROM analyzer_tables WHERE name = $1 LIMIT 1", table_name
            )
            if table_id:
                await conn.execute(
                    """INSERT INTO analyzer_etl_table_refs (ast_node_id, table_id, ref_type)
                       VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                    ast_node_id, table_id, ref_type,
                )
