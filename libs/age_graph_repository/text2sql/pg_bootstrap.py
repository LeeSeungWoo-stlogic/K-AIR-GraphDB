"""
PostgreSQL 스키마 부트스트랩 — ensure_neo4j_schema() + Neo4jQueryRepository.setup_constraints() 대체.

서버 기동 시 t2s_* 테이블 존재를 확인하고, 없으면 DDL을 실행한다.
pgvector HNSW 인덱스는 DDL 내 IF NOT EXISTS로 멱등 처리된다.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .pg_connection import PgConnection

logger = logging.getLogger(__name__)

_DDL_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "docker", "age-pgvector", "init", "04-text2sql-tables.sql"
)


async def ensure_pg_schema(
    pg_conn: PgConnection,
    *,
    ddl_path: Optional[str] = None,
) -> dict:
    """text2sql용 PostgreSQL 테이블/인덱스가 존재하는지 확인하고, 없으면 DDL을 실행.

    Returns:
        {"ok": True/False, "tables_checked": int, "detail": ...}
    """
    required_tables = [
        "t2s_tables", "t2s_columns", "t2s_fk_constraints",
        "t2s_queries", "t2s_query_table_usage", "t2s_query_column_usage",
        "t2s_value_mappings",
    ]

    try:
        rows = await pg_conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY($1)
            """,
            required_tables,
        )
        existing = {r["table_name"] for r in rows}
        missing = [t for t in required_tables if t not in existing]

        if missing:
            logger.info("Missing text2sql tables: %s — running DDL", missing)
            ddl_file = ddl_path or _DDL_FILE
            if os.path.exists(ddl_file):
                with open(ddl_file, "r", encoding="utf-8") as f:
                    ddl_sql = f.read()
                await pg_conn.execute(ddl_sql)
                logger.info("DDL executed from %s", ddl_file)
            else:
                logger.warning("DDL file not found: %s — tables may need manual creation", ddl_file)
                return {"ok": False, "tables_checked": len(required_tables), "detail": f"DDL file missing: {ddl_file}"}

            rows2 = await pg_conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY($1)
                """,
                required_tables,
            )
            existing2 = {r["table_name"] for r in rows2}
            still_missing = [t for t in required_tables if t not in existing2]
            if still_missing:
                return {"ok": False, "tables_checked": len(required_tables), "detail": f"Still missing: {still_missing}"}

        logger.info("text2sql PG schema bootstrap OK — %d tables verified", len(required_tables))
        return {"ok": True, "tables_checked": len(required_tables), "detail": "all present"}

    except Exception as exc:
        logger.error("ensure_pg_schema failed: %s", exc, exc_info=True)
        return {"ok": False, "tables_checked": 0, "detail": str(exc)}
