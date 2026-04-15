"""
PgSchemaManageService — schema_manage_service.py의 Neo4j 전환.

테이블/컬럼 조회, 관계 CRUD, 설명 업데이트, 벡터 검색을 PostgreSQL로 전환.
"""

import logging
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

ALLOWED_RELATIONSHIP_TYPES = frozenset({
    "FK_TO_TABLE", "ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY",
})


class PgSchemaManageService:
    """PostgreSQL 기반 스키마 관리 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def search_tables_by_semantic(
        self, query_embedding: List[float], limit: int = 10
    ) -> List[Dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT name, schema_name AS schema, description,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM analyzer_tables
                   WHERE embedding IS NOT NULL AND description IS NOT NULL AND description <> ''
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                str(query_embedding),
                limit,
            )
            return [
                {
                    "name": r["name"],
                    "schema": r["schema"] or "public",
                    "description": (r["description"] or "")[:200],
                    "similarity": round(float(r["similarity"]), 4),
                }
                for r in rows
                if float(r["similarity"]) >= 0.3
            ]

    async def fetch_schema_tables(
        self, search: Optional[str] = None, schema: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        conditions = []
        args: list = []
        idx = 1

        if schema:
            conditions.append(f"t.schema_name = ${idx}")
            args.append(schema)
            idx += 1
        if search:
            conditions.append(f"(lower(t.name) LIKE ${idx} OR lower(t.description) LIKE ${idx})")
            args.append(f"%{search.lower()}%")
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        args.append(limit)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT t.name, t.schema_name AS schema, t.datasource, t.description,
                           t.description_source, t.analyzed_description,
                           (SELECT count(*) FROM analyzer_columns c WHERE c.table_id = t.id) AS column_count
                    FROM analyzer_tables t
                    WHERE {where}
                    ORDER BY t.datasource, t.schema_name, t.name
                    LIMIT ${idx}""",
                *args,
            )
            return [dict(r) for r in rows]

    async def fetch_table_columns(self, table_name: str, schema: str = "") -> List[Dict]:
        async with self._pool.acquire() as conn:
            if schema:
                rows = await conn.fetch(
                    """SELECT c.name, t.name AS table_name, c.dtype, c.nullable, c.description,
                              c.description_source, c.analyzed_description
                       FROM analyzer_columns c
                       JOIN analyzer_tables t ON t.id = c.table_id
                       WHERE t.name = $1 AND t.schema_name = $2
                       ORDER BY c.name""",
                    table_name, schema,
                )
            else:
                rows = await conn.fetch(
                    """SELECT c.name, t.name AS table_name, c.dtype, c.nullable, c.description,
                              c.description_source, c.analyzed_description
                       FROM analyzer_columns c
                       JOIN analyzer_tables t ON t.id = c.table_id
                       WHERE t.name = $1
                       ORDER BY c.name""",
                    table_name,
                )
            return [dict(r) for r in rows]

    async def fetch_schema_relationships(self) -> List[Dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT t1.name AS from_table, t1.schema_name AS from_schema, r.source_column AS from_column,
                          t2.name AS to_table, t2.schema_name AS to_schema, r.target_column AS to_column,
                          r.rel_type AS relationship_type, r.description
                   FROM analyzer_table_relationships r
                   JOIN analyzer_tables t1 ON t1.id = r.from_table_id
                   JOIN analyzer_tables t2 ON t2.id = r.to_table_id
                   WHERE r.rel_type IN ('FK_TO_TABLE', 'ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_ONE', 'MANY_TO_MANY')
                   ORDER BY t1.name, t2.name"""
            )
            return [dict(r) for r in rows]

    async def create_schema_relationship(
        self,
        from_table: str, from_schema: str, from_column: str,
        to_table: str, to_schema: str, to_column: str,
        relationship_type: str = "FK_TO_TABLE",
        description: str = "",
    ) -> Dict:
        if relationship_type not in ALLOWED_RELATIONSHIP_TYPES:
            raise ValueError(f"허용되지 않는 관계 타입: {relationship_type}")

        async with self._pool.acquire() as conn:
            from_id = await conn.fetchval(
                "SELECT id FROM analyzer_tables WHERE name = $1 AND schema_name = $2", from_table, from_schema
            )
            to_id = await conn.fetchval(
                "SELECT id FROM analyzer_tables WHERE name = $1 AND schema_name = $2", to_table, to_schema
            )
            if not from_id or not to_id:
                raise ValueError("테이블을 찾을 수 없습니다.")

            await conn.execute(
                """INSERT INTO analyzer_table_relationships
                     (from_table_id, to_table_id, rel_type, source_column, target_column, source, description)
                   VALUES ($1, $2, $3, $4, $5, 'user', $6)
                   ON CONFLICT (from_table_id, to_table_id, rel_type, source_column, target_column)
                     DO UPDATE SET description = EXCLUDED.description, source = 'user'""",
                from_id, to_id, relationship_type, from_column, to_column, description,
            )
            return {"message": "관계가 생성되었습니다.", "created": True}

    async def delete_schema_relationship(
        self, from_table: str, from_column: str, to_table: str, to_column: str
    ) -> Dict:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """DELETE FROM analyzer_table_relationships r
                   USING analyzer_tables t1, analyzer_tables t2
                   WHERE r.from_table_id = t1.id AND r.to_table_id = t2.id
                     AND t1.name = $1 AND t2.name = $2
                     AND r.source_column = $3 AND r.target_column = $4""",
                from_table, to_table, from_column, to_column,
            )
            deleted = int(result.split()[-1]) if result else 0
            return {"message": f"{deleted}개 관계가 삭제되었습니다.", "deleted": deleted}

    async def update_table_description(
        self, table_name: str, schema: str, description: str, embedding: Optional[List[float]] = None
    ) -> Dict:
        async with self._pool.acquire() as conn:
            if embedding:
                await conn.execute(
                    """UPDATE analyzer_tables
                       SET description = $1, description_source = 'user', embedding = $4::vector, updated_at = now()
                       WHERE name = $2 AND (schema_name = $3 OR schema_name IS NULL)""",
                    description, table_name, schema, str(embedding),
                )
            else:
                await conn.execute(
                    """UPDATE analyzer_tables
                       SET description = $1, description_source = 'user', updated_at = now()
                       WHERE name = $2 AND (schema_name = $3 OR schema_name IS NULL)""",
                    description, table_name, schema,
                )
            return {"message": "테이블 설명이 업데이트되었습니다.", "updated": True}

    async def update_column_description(
        self, table_name: str, column_name: str, description: str
    ) -> Dict:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE analyzer_columns c
                   SET description = $1, description_source = 'user', updated_at = now()
                   FROM analyzer_tables t
                   WHERE c.table_id = t.id AND t.name = $2 AND c.name = $3""",
                description, table_name, column_name,
            )
            return {"message": "컬럼 설명이 업데이트되었습니다.", "updated": True}

    async def update_table_embedding(self, table_name: str, embedding: List[float]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE analyzer_tables SET embedding = $1::vector WHERE name = $2",
                str(embedding), table_name,
            )

    async def fetch_table_references(self, table_name: str) -> List[Dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT
                          proc.name AS procedure_name,
                          proc.node_type AS procedure_type,
                          stmt.start_line,
                          ref.ref_type AS access_type,
                          stmt.node_type AS statement_type,
                          proc.file_name,
                          proc.directory AS file_directory
                   FROM analyzer_ast_table_refs ref
                   JOIN analyzer_tables t ON t.id = ref.table_id AND t.name = $1
                   JOIN analyzer_ast_nodes stmt ON stmt.id = ref.ast_node_id
                   LEFT JOIN analyzer_ast_nodes proc ON proc.id = stmt.parent_id
                   ORDER BY proc.name, stmt.start_line""",
                table_name,
            )
            return [dict(r) for r in rows]
