"""E2E: K-AIR-text2sql × K-AIR-GraphDB 연동 테스트"""

import pytest

from age_graph_repository.text2sql import PgConnection, ensure_pg_schema


@pytest.fixture
async def pg_t2s():
    conn = PgConnection(
        host="localhost",
        port=15432,
        database="kair_graphdb",
        user="kair",
        password="kair_pass",
        min_size=2,
        max_size=5,
    )
    await conn.connect()
    yield conn
    await conn.close()


class TestText2SqlE2E:

    async def test_pg_connection(self, pg_t2s):
        val = await pg_t2s.fetchval("SELECT 1")
        assert val == 1

    async def test_schema_bootstrap(self, pg_t2s):
        result = await ensure_pg_schema(pg_t2s)
        assert result is not None

    async def test_t2s_tables_exist(self, pg_t2s):
        row = await pg_t2s.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name LIKE 't2s_%'"
        )
        assert row >= 5

    async def test_table_crud(self, pg_t2s):
        await pg_t2s.execute(
            """INSERT INTO t2s_tables (db, schema_name, name, description)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (db, schema_name, name) DO UPDATE SET description = EXCLUDED.description""",
            "e2e_db", "public", "e2e_orders", "E2E 테스트 테이블",
        )
        row = await pg_t2s.fetchrow(
            "SELECT * FROM t2s_tables WHERE name = $1", "e2e_orders"
        )
        assert row is not None
        assert row["description"] == "E2E 테스트 테이블"

    async def test_column_crud(self, pg_t2s):
        table_row = await pg_t2s.fetchrow(
            "SELECT id FROM t2s_tables WHERE name = $1", "e2e_orders"
        )
        if table_row:
            fqn = "e2e_db.public.e2e_orders.e2e_order_id"
            await pg_t2s.execute(
                """INSERT INTO t2s_columns (table_id, fqn, name, dtype, description)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (fqn) DO NOTHING""",
                table_row["id"], fqn, "e2e_order_id", "INTEGER", "주문 ID",
            )
            cols = await pg_t2s.fetch(
                "SELECT * FROM t2s_columns WHERE table_id = $1", table_row["id"]
            )
            assert len(cols) >= 1

    async def test_query_history_crud(self, pg_t2s):
        import uuid
        qid = f"e2e_{uuid.uuid4().hex[:8]}"
        await pg_t2s.execute(
            """INSERT INTO t2s_queries (id, question, sql_text, status)
               VALUES ($1, $2, $3, $4)""",
            qid, "E2E 테스트 질문", "SELECT 1", "completed",
        )
        rows = await pg_t2s.fetch(
            "SELECT * FROM t2s_queries WHERE question LIKE $1", "%E2E%"
        )
        assert len(rows) >= 1

    async def test_cleanup(self, pg_t2s):
        await pg_t2s.execute("DELETE FROM t2s_queries WHERE question LIKE '%E2E%'")
        await pg_t2s.execute(
            "DELETE FROM t2s_columns WHERE table_id IN (SELECT id FROM t2s_tables WHERE name LIKE 'e2e_%')"
        )
        await pg_t2s.execute("DELETE FROM t2s_tables WHERE name LIKE 'e2e_%'")
