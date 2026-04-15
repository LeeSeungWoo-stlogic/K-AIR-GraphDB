"""
PgMetadataService — metadata_enrichment_service.py의 Neo4j 전환.

테이블/컬럼 description 업데이트, FK 관계 저장, 기존 FK 조회를 PostgreSQL로 전환.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)

DESCRIPTION_SOURCE = "sample_data_inference"


class PgMetadataService:
    """PostgreSQL 기반 메타데이터 보강 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_tables_without_description(
        self, schema_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        conditions = ["(t.description IS NULL OR t.description = '' OR t.description = 'N/A')"]
        args: list = []
        idx = 1
        if schema_name:
            conditions.append(f"t.schema_name = ${idx}")
            args.append(schema_name)
            idx += 1

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT t.id, t.name AS table_name, t.schema_name, t.db
                    FROM analyzer_tables t WHERE {' AND '.join(conditions)}
                    ORDER BY t.name""",
                *args,
            )
            return [dict(r) for r in rows]

    async def get_table_columns_info(self, table_name: str, schema_name: str) -> List[Dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.name AS column_name, c.dtype AS data_type, c.is_primary_key,
                          c.description, c.nullable
                   FROM analyzer_columns c
                   JOIN analyzer_tables t ON t.id = c.table_id
                   WHERE t.name = $1 AND t.schema_name = $2
                   ORDER BY c.name""",
                table_name, schema_name,
            )
            return [dict(r) for r in rows]

    async def get_all_tables_with_columns(self) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            tables = await conn.fetch(
                """SELECT t.id, t.name AS table_name, t.schema_name
                   FROM analyzer_tables t ORDER BY t.name"""
            )
            result = []
            for t in tables:
                cols = await conn.fetch(
                    """SELECT name AS column_name, dtype AS data_type, is_primary_key
                       FROM analyzer_columns WHERE table_id = $1""",
                    t["id"],
                )
                result.append({
                    "table_name": t["table_name"],
                    "schema_name": t["schema_name"],
                    "columns": [dict(c) for c in cols],
                })
            return result

    async def update_table_description(
        self, table_name: str, schema_name: str, description: str
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE analyzer_tables
                   SET description = $1, description_source = $2, updated_at = now()
                   WHERE name = $3 AND schema_name = $4
                     AND (description IS NULL OR description = '' OR description = 'N/A')""",
                description, DESCRIPTION_SOURCE, table_name, schema_name,
            )

    async def update_column_descriptions(
        self, table_name: str, schema_name: str, column_descs: Dict[str, str]
    ) -> int:
        updated = 0
        async with self._pool.acquire() as conn:
            for col_name, col_desc in column_descs.items():
                result = await conn.execute(
                    """UPDATE analyzer_columns c
                       SET description = $1, description_source = $2, updated_at = now()
                       FROM analyzer_tables t
                       WHERE c.table_id = t.id AND t.name = $3 AND t.schema_name = $4 AND c.name = $5
                         AND (c.description IS NULL OR c.description = '' OR c.description = 'N/A')""",
                    col_desc, DESCRIPTION_SOURCE, table_name, schema_name, col_name,
                )
                if "UPDATE 1" in result:
                    updated += 1
        return updated

    async def get_existing_fk_set(self) -> set:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT t1.schema_name || '.' || t1.name AS from_table,
                          t2.schema_name || '.' || t2.name AS to_table,
                          r.source_column AS from_column,
                          r.target_column AS to_column
                   FROM analyzer_table_relationships r
                   JOIN analyzer_tables t1 ON t1.id = r.from_table_id
                   JOIN analyzer_tables t2 ON t2.id = r.to_table_id
                   WHERE r.rel_type = 'FK_TO_TABLE'"""
            )
            return {
                (r["from_table"] or "", r["to_table"] or "", r["from_column"] or "", r["to_column"] or "")
                for r in rows
            }

    async def save_fk_relationship(self, fk_info: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                from_id = await conn.fetchval(
                    "SELECT id FROM analyzer_tables WHERE name=$1 AND schema_name=$2",
                    fk_info["from_table"], fk_info["from_schema"],
                )
                to_id = await conn.fetchval(
                    "SELECT id FROM analyzer_tables WHERE name=$1 AND schema_name=$2",
                    fk_info["to_table"], fk_info["to_schema"],
                )
                if not from_id or not to_id:
                    return

                await conn.execute(
                    """INSERT INTO analyzer_table_relationships
                         (from_table_id, to_table_id, rel_type, source_column, target_column,
                          source, rel_subtype, similarity, match_ratio, matched_count, total_samples)
                       VALUES ($1, $2, 'FK_TO_TABLE', $3, $4, $5, 'many_to_one', $6, $7, $8, $9)
                       ON CONFLICT (from_table_id, to_table_id, rel_type, source_column, target_column)
                         DO UPDATE SET source = CASE WHEN analyzer_table_relationships.source = 'ddl' THEN 'ddl' ELSE EXCLUDED.source END""",
                    from_id, to_id,
                    fk_info.get("from_column", ""), fk_info.get("to_column", ""),
                    DESCRIPTION_SOURCE,
                    fk_info.get("similarity", 0.0), fk_info.get("match_ratio", 0.0),
                    fk_info.get("matched_count", 0), fk_info.get("total_samples", 0),
                )

                from_fqn = f"{fk_info['from_schema']}.{fk_info['from_table']}.{fk_info['from_column']}"
                to_fqn = f"{fk_info['to_schema']}.{fk_info['to_table']}.{fk_info['to_column']}"

                from_col_id = await conn.fetchval(
                    """INSERT INTO analyzer_columns (fqn, table_id, name, dtype)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (fqn) DO UPDATE SET table_id = COALESCE(EXCLUDED.table_id, analyzer_columns.table_id)
                       RETURNING id""",
                    from_fqn, from_id, fk_info.get("from_column", ""), fk_info.get("from_type", ""),
                )
                to_col_id = await conn.fetchval(
                    """INSERT INTO analyzer_columns (fqn, table_id, name, dtype)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (fqn) DO UPDATE SET table_id = COALESCE(EXCLUDED.table_id, analyzer_columns.table_id)
                       RETURNING id""",
                    to_fqn, to_id, fk_info.get("to_column", ""), fk_info.get("to_type", ""),
                )

                if from_col_id and to_col_id:
                    await conn.execute(
                        """INSERT INTO analyzer_column_relationships (from_column_id, to_column_id, rel_type, source)
                           VALUES ($1, $2, 'FK_TO_COLUMN', $3)
                           ON CONFLICT DO NOTHING""",
                        from_col_id, to_col_id, DESCRIPTION_SOURCE,
                    )
