"""E2E: K-AIR-analyzer × K-AIR-GraphDB 연동 테스트"""

import pytest
import asyncpg

from age_graph_repository.analyzer import (
    PgAnalyzerClient,
    PgGraphQueryService,
    PgGlossaryService,
    PgSchemaManageService,
    PgRelatedTablesService,
    PgLineageService,
    PgMetadataService,
    PgBusinessCalendarService,
    PgPhaseDDL,
)


@pytest.fixture
async def analyzer_pool():
    pool = await asyncpg.create_pool(
        "postgresql://kair:kair_pass@localhost:15432/kair_graphdb",
        min_size=2,
        max_size=5,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def clean_analyzer(analyzer_pool):
    async with analyzer_pool.acquire() as conn:
        await conn.execute("DELETE FROM analyzer_non_business_days WHERE calendar_id IN (SELECT id FROM analyzer_business_calendars WHERE name LIKE 'E2E%')")
        await conn.execute("DELETE FROM analyzer_business_calendars WHERE name LIKE 'E2E%'")
        await conn.execute("DELETE FROM analyzer_lineage_edges WHERE edge_type LIKE 'E2E%'")
        await conn.execute("DELETE FROM analyzer_lineage_nodes WHERE name LIKE 'E2E%'")
        await conn.execute("DELETE FROM analyzer_terms WHERE name LIKE 'E2E%'")
        await conn.execute("DELETE FROM analyzer_glossaries WHERE name LIKE 'E2E%'")
        await conn.execute("DELETE FROM analyzer_columns WHERE name LIKE 'e2e_%'")
        await conn.execute("""
            DELETE FROM analyzer_table_relationships
            WHERE from_table_id IN (SELECT id FROM analyzer_tables WHERE name LIKE 'e2e_%')
               OR to_table_id IN (SELECT id FROM analyzer_tables WHERE name LIKE 'e2e_%')
        """)
        await conn.execute("DELETE FROM analyzer_tables WHERE name LIKE 'e2e_%'")
        await conn.execute("DELETE FROM analyzer_data_sources WHERE name LIKE 'e2e_%'")


class TestAnalyzerE2E:

    async def test_pg_client(self, analyzer_pool, clean_analyzer):
        client = PgAnalyzerClient(analyzer_pool)
        results = await client.execute_queries(["SELECT 1 AS val"])
        assert len(results) == 1
        assert results[0][0]["val"] == 1

    async def test_analyzer_tables_exist(self, analyzer_pool, clean_analyzer):
        count = await analyzer_pool.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name LIKE 'analyzer_%'"
        )
        assert count >= 15

    async def test_phase_ddl_save(self, analyzer_pool, clean_analyzer):
        ddl = PgPhaseDDL(analyzer_pool)
        result = await ddl.save_ddl_results(
            schemas_data=[{"db": "e2e_db", "name": "public"}],
            tables_data=[{"db": "e2e_db", "schema": "public", "name": "e2e_orders", "description": "E2E"}],
            columns_data=[{
                "table_db": "e2e_db", "table_schema": "public", "table_name": "e2e_orders",
                "fqn": "e2e_db.public.e2e_orders.e2e_order_id",
                "name": "e2e_order_id", "dtype": "INTEGER", "description": "PK",
            }],
            fks_data=[],
            datasource_name="e2e_source",
        )
        assert result is not None

    async def test_graph_query_service(self, analyzer_pool, clean_analyzer):
        svc = PgGraphQueryService(analyzer_pool)
        result = await svc.check_graph_data_exists()
        assert isinstance(result, dict)
        assert "hasData" in result

    async def test_glossary_crud(self, analyzer_pool, clean_analyzer):
        svc = PgGlossaryService(analyzer_pool)
        gid = await svc.create_glossary("E2E Glossary", "테스트용", "Test")
        assert gid is not None

        result = await svc.fetch_all_glossaries()
        glossaries = result.get("glossaries", []) if isinstance(result, dict) else result
        names = [g.get("name", "") if isinstance(g, dict) else "" for g in glossaries]
        assert "E2E Glossary" in names

    async def test_schema_manage_service(self, analyzer_pool, clean_analyzer):
        svc = PgSchemaManageService(analyzer_pool)
        tables = await svc.fetch_schema_tables()
        assert isinstance(tables, list)

    async def test_related_tables_service(self, analyzer_pool, clean_analyzer):
        svc = PgRelatedTablesService(analyzer_pool)
        result = await svc.fetch_related_tables_unified({
            "mode": "ROBO",
            "tableName": "e2e_orders",
            "schemaName": "public",
        })
        assert isinstance(result, dict)

    async def test_lineage_service(self, analyzer_pool, clean_analyzer):
        svc = PgLineageService(analyzer_pool)
        await svc.save_lineage(
            proc_name="E2E_ETL",
            source_tables=["e2e_source_table"],
            target_tables=["e2e_target_table"],
        )

        graph = await svc.fetch_lineage_graph()
        assert "nodes" in graph
        assert "edges" in graph

    async def test_metadata_service(self, analyzer_pool, clean_analyzer):
        svc = PgMetadataService(analyzer_pool)
        tables = await svc.get_tables_without_description()
        assert isinstance(tables, list)

    async def test_business_calendar_service(self, analyzer_pool, clean_analyzer):
        svc = PgBusinessCalendarService(analyzer_pool)
        result = await svc.create_calendar("E2E Calendar", "테스트")
        cid = result.get("id") if isinstance(result, dict) else result
        assert cid is not None

        result2 = await svc.fetch_all_calendars()
        cal_list = result2.get("calendars", []) if isinstance(result2, dict) else result2
        names = [c.get("name", "") for c in cal_list]
        assert "E2E Calendar" in names

    async def test_cleanup(self, analyzer_pool):
        async with analyzer_pool.acquire() as conn:
            await conn.execute("DELETE FROM analyzer_non_business_days WHERE calendar_id IN (SELECT id FROM analyzer_business_calendars WHERE name LIKE 'E2E%')")
            await conn.execute("DELETE FROM analyzer_business_calendars WHERE name LIKE 'E2E%'")
            await conn.execute("DELETE FROM analyzer_lineage_edges WHERE edge_type LIKE 'E2E%'")
            await conn.execute("DELETE FROM analyzer_lineage_nodes WHERE name LIKE 'E2E%'")
            await conn.execute("DELETE FROM analyzer_terms WHERE name LIKE 'E2E%'")
            await conn.execute("DELETE FROM analyzer_glossaries WHERE name LIKE 'E2E%'")
            await conn.execute("DELETE FROM analyzer_columns WHERE name LIKE 'e2e_%'")
            await conn.execute("""
                DELETE FROM analyzer_table_relationships
                WHERE from_table_id IN (SELECT id FROM analyzer_tables WHERE name LIKE 'e2e_%')
                   OR to_table_id IN (SELECT id FROM analyzer_tables WHERE name LIKE 'e2e_%')
            """)
            await conn.execute("DELETE FROM analyzer_tables WHERE name LIKE 'e2e_%'")
            await conn.execute("DELETE FROM analyzer_data_sources WHERE name LIKE 'e2e_%'")
