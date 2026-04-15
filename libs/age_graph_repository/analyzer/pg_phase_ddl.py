"""
PgPhaseDDL — phase_ddl.py의 Neo4j UNWIND 배치를 PostgreSQL bulk INSERT/UPSERT로 전환.

원본 phase_ddl.py의 7단계 UNWIND 배치를 SQL로 재구현:
  1. 스키마 MERGE → INSERT ... ON CONFLICT DO UPDATE
  2. DataSource MERGE + HAS_SCHEMA → INSERT + analyzer_schema_datasource
  3. 테이블 MERGE → INSERT ... ON CONFLICT DO UPDATE
  4. 테이블-스키마 BELONGS_TO → 이미 schema_name으로 연결됨
  5. 컬럼 MERGE → INSERT ... ON CONFLICT DO UPDATE
  6. 테이블-컬럼 HAS_COLUMN → analyzer_columns.table_id FK
  7. FK_TO_TABLE → analyzer_table_relationships INSERT
"""

import logging
from typing import Any, Dict, List, Tuple

import asyncpg

logger = logging.getLogger(__name__)


class PgPhaseDDL:
    """DDL 파싱 결과를 PostgreSQL analyzer 테이블에 저장"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_ddl_results(
        self,
        schemas_data: List[Dict[str, Any]],
        tables_data: List[Dict[str, Any]],
        columns_data: List[Dict[str, Any]],
        fks_data: List[Dict[str, Any]],
        datasource_name: str = "",
    ) -> Dict[str, Any]:
        """DDL 파싱 결과를 한 트랜잭션으로 저장.

        Returns:
            {"schemas": N, "tables": N, "columns": N, "fks": N, "Nodes": [...], "Relationships": [...]}
        """
        stats = {"schemas": 0, "tables": 0, "columns": 0, "fks": 0}
        nodes: Dict[int, Dict] = {}
        relationships: List[Dict] = []

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1) DataSource
                ds_id = None
                if datasource_name:
                    ds_id = await conn.fetchval(
                        """INSERT INTO analyzer_data_sources (name)
                           VALUES ($1)
                           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                           RETURNING id""",
                        datasource_name,
                    )

                # 2) Schemas
                for s in schemas_data:
                    sid = await conn.fetchval(
                        """INSERT INTO analyzer_schemas (db, name, datasource)
                           VALUES ($1, $2, $3)
                           ON CONFLICT (db, name) DO UPDATE
                             SET datasource = CASE WHEN EXCLUDED.datasource <> '' THEN EXCLUDED.datasource
                                                   ELSE analyzer_schemas.datasource END
                           RETURNING id""",
                        s["db"],
                        s["name"],
                        s.get("datasource", ""),
                    )
                    stats["schemas"] += 1

                    if ds_id and sid:
                        await conn.execute(
                            """INSERT INTO analyzer_schema_datasource (schema_id, datasource_id)
                               VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                            sid,
                            ds_id,
                        )

                # 3) Tables
                table_id_cache: Dict[Tuple[str, str, str], int] = {}
                for t in tables_data:
                    tid = await conn.fetchval(
                        """INSERT INTO analyzer_tables (db, schema_name, name, description, description_source, table_type, datasource)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)
                           ON CONFLICT (db, schema_name, name) DO UPDATE
                             SET description = EXCLUDED.description,
                                 description_source = EXCLUDED.description_source,
                                 table_type = EXCLUDED.table_type,
                                 datasource = CASE WHEN EXCLUDED.datasource <> '' THEN EXCLUDED.datasource
                                                   ELSE analyzer_tables.datasource END,
                                 updated_at = now()
                           RETURNING id""",
                        t["db"],
                        t["schema"],
                        t["name"],
                        t.get("description", ""),
                        t.get("description_source", ""),
                        t.get("table_type", "BASE TABLE"),
                        t.get("datasource", ""),
                    )
                    table_id_cache[(t["db"], t["schema"], t["name"])] = tid
                    stats["tables"] += 1
                    nodes[tid] = {
                        "Node ID": str(tid),
                        "Labels": ["Analyzer_Table"],
                        "Properties": {"name": t["name"], "schema": t["schema"], "db": t["db"]},
                    }

                # 4) Columns
                col_id_cache: Dict[str, int] = {}
                for c in columns_data:
                    t_key = (c["table_db"], c["table_schema"], c["table_name"])
                    table_id = table_id_cache.get(t_key)
                    if not table_id:
                        table_id = await conn.fetchval(
                            "SELECT id FROM analyzer_tables WHERE db=$1 AND schema_name=$2 AND name=$3",
                            c["table_db"],
                            c["table_schema"],
                            c["table_name"],
                        )

                    cid = await conn.fetchval(
                        """INSERT INTO analyzer_columns (fqn, table_id, name, dtype, description, description_source,
                                                         nullable, is_primary_key, pk_constraint, datasource)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                           ON CONFLICT (fqn) DO UPDATE
                             SET name = EXCLUDED.name,
                                 dtype = EXCLUDED.dtype,
                                 description = EXCLUDED.description,
                                 description_source = EXCLUDED.description_source,
                                 nullable = EXCLUDED.nullable,
                                 is_primary_key = EXCLUDED.is_primary_key,
                                 pk_constraint = COALESCE(NULLIF(EXCLUDED.pk_constraint, ''), analyzer_columns.pk_constraint),
                                 datasource = CASE WHEN EXCLUDED.datasource <> '' THEN EXCLUDED.datasource
                                                   ELSE analyzer_columns.datasource END,
                                 table_id = COALESCE(EXCLUDED.table_id, analyzer_columns.table_id),
                                 updated_at = now()
                           RETURNING id""",
                        c["fqn"],
                        table_id,
                        c["name"],
                        c.get("dtype", ""),
                        c.get("description", ""),
                        c.get("description_source", ""),
                        c.get("nullable", True),
                        c.get("is_primary_key", False),
                        c.get("pk_constraint", ""),
                        c.get("datasource", ""),
                    )
                    col_id_cache[c["fqn"]] = cid
                    stats["columns"] += 1

                # 5) FK relationships
                for fk in fks_data:
                    from_key = (fk["from_db"], fk["from_schema"], fk["from_table"])
                    to_key = (fk["to_db"], fk.get("to_schema", ""), fk.get("to_table", ""))

                    from_id = table_id_cache.get(from_key)
                    if not from_id:
                        from_id = await conn.fetchval(
                            "SELECT id FROM analyzer_tables WHERE db=$1 AND schema_name=$2 AND name=$3",
                            *from_key,
                        )

                    to_id = table_id_cache.get(to_key)
                    if not to_id:
                        to_id = await conn.fetchval(
                            "SELECT id FROM analyzer_tables WHERE db=$1 AND schema_name=$2 AND name=$3",
                            *to_key,
                        )
                        if not to_id:
                            to_id = await conn.fetchval(
                                """INSERT INTO analyzer_tables (db, schema_name, name)
                                   VALUES ($1, $2, $3)
                                   ON CONFLICT (db, schema_name, name) DO UPDATE SET name = EXCLUDED.name
                                   RETURNING id""",
                                fk["to_db"],
                                fk.get("to_schema", ""),
                                fk.get("to_table", ""),
                            )
                            table_id_cache[to_key] = to_id

                    if from_id and to_id:
                        rel_id = await conn.fetchval(
                            """INSERT INTO analyzer_table_relationships
                                 (from_table_id, to_table_id, rel_type, source_column, target_column, source, rel_subtype)
                               VALUES ($1, $2, 'FK_TO_TABLE', $3, $4, 'ddl', 'many_to_one')
                               ON CONFLICT (from_table_id, to_table_id, rel_type, source_column, target_column)
                                 DO UPDATE SET source = 'ddl'
                               RETURNING id""",
                            from_id,
                            to_id,
                            fk.get("from_column", ""),
                            fk.get("to_column", ""),
                        )
                        stats["fks"] += 1
                        if rel_id:
                            relationships.append({
                                "Relationship ID": str(rel_id),
                                "Type": "FK_TO_TABLE",
                                "Start Node ID": str(from_id),
                                "End Node ID": str(to_id),
                                "Properties": {
                                    "sourceColumn": fk.get("from_column", ""),
                                    "targetColumn": fk.get("to_column", ""),
                                },
                            })

        return {
            **stats,
            "Nodes": list(nodes.values()),
            "Relationships": relationships,
        }
