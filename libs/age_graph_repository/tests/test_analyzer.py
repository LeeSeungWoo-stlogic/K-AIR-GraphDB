"""
Phase 4 통합 테스트 — Analyzer 서비스 PostgreSQL 전환 검증.

age-pgvector Docker 컨테이너(localhost:15432)에 연결하여 테스트합니다.
"""

import os
import pytest
import pytest_asyncio
import asyncpg

from age_graph_repository.analyzer.pg_analyzer_client import PgAnalyzerClient
from age_graph_repository.analyzer.pg_phase_ddl import PgPhaseDDL
from age_graph_repository.analyzer.pg_graph_query_service import PgGraphQueryService
from age_graph_repository.analyzer.pg_glossary_service import PgGlossaryService
from age_graph_repository.analyzer.pg_schema_manage_service import PgSchemaManageService
from age_graph_repository.analyzer.pg_related_tables_service import PgRelatedTablesService
from age_graph_repository.analyzer.pg_lineage_service import PgLineageService
from age_graph_repository.analyzer.pg_metadata_service import PgMetadataService
from age_graph_repository.analyzer.pg_business_calendar_service import PgBusinessCalendarService

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "15432"))
PG_USER = os.getenv("PG_USER", "kair")
PG_PASS = os.getenv("PG_PASS", "kair_pass")
PG_DB = os.getenv("PG_DB", "kair_graphdb")


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS, database=PG_DB,
        min_size=1, max_size=3,
    )
    yield p
    await p.close()


@pytest_asyncio.fixture
async def clean_db(pool):
    """각 테스트 전 analyzer 테이블 초기화"""
    async with pool.acquire() as conn:
        for table in [
            "analyzer_etl_table_refs",
            "analyzer_ast_table_refs",
            "analyzer_ast_edges",
            "analyzer_user_stories",
            "analyzer_ast_nodes",
            "analyzer_column_relationships",
            "analyzer_table_relationships",
            "analyzer_columns",
            "analyzer_tables",
            "analyzer_lineage_edges",
            "analyzer_lineage_nodes",
            "analyzer_schema_datasource",
            "analyzer_schemas",
            "analyzer_data_sources",
            "analyzer_term_owners",
            "analyzer_term_tags",
            "analyzer_term_domains",
            "analyzer_terms",
            "analyzer_glossaries",
            "analyzer_domains",
            "analyzer_owners",
            "analyzer_tags",
            "analyzer_holidays",
            "analyzer_non_business_days",
            "analyzer_business_calendars",
        ]:
            try:
                await conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
    yield


# ===========================================================================
# PgAnalyzerClient 기본 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_analyzer_client_execute_queries(pool, clean_db):
    client = PgAnalyzerClient(pool)
    result = await client.execute_queries(["SELECT 1 AS val"])
    assert len(result) == 1
    assert result[0][0]["val"] == 1


@pytest.mark.asyncio
async def test_analyzer_client_execute_with_params(pool, clean_db):
    client = PgAnalyzerClient(pool)
    result = await client.execute_with_params(
        "SELECT $x::int + $y::int AS total",
        {"x": 10, "y": 20},
    )
    assert result[0]["total"] == 30


@pytest.mark.asyncio
async def test_analyzer_client_check_nodes_exist(pool, clean_db):
    client = PgAnalyzerClient(pool)
    exists = await client.check_nodes_exist([("dir1", "file1.sql")])
    assert exists is False


# ===========================================================================
# PgPhaseDDL 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_phase_ddl_save(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    result = await ddl.save_ddl_results(
        schemas_data=[{"db": "testdb", "name": "public", "datasource": "ds1"}],
        tables_data=[
            {"db": "testdb", "schema": "public", "name": "orders", "description": "주문 테이블", "datasource": "ds1"},
            {"db": "testdb", "schema": "public", "name": "customers", "description": "고객 테이블", "datasource": "ds1"},
        ],
        columns_data=[
            {"fqn": "ds1.public.orders.id", "name": "id", "dtype": "int", "is_primary_key": True,
             "table_db": "testdb", "table_schema": "public", "table_name": "orders"},
            {"fqn": "ds1.public.orders.customer_id", "name": "customer_id", "dtype": "int",
             "table_db": "testdb", "table_schema": "public", "table_name": "orders"},
            {"fqn": "ds1.public.customers.id", "name": "id", "dtype": "int", "is_primary_key": True,
             "table_db": "testdb", "table_schema": "public", "table_name": "customers"},
        ],
        fks_data=[
            {"from_db": "testdb", "from_schema": "public", "from_table": "orders", "from_column": "customer_id",
             "to_db": "testdb", "to_schema": "public", "to_table": "customers", "to_column": "id"},
        ],
        datasource_name="ds1",
    )
    assert result["schemas"] == 1
    assert result["tables"] == 2
    assert result["columns"] == 3
    assert result["fks"] == 1
    assert len(result["Nodes"]) >= 2
    assert len(result["Relationships"]) >= 1


# ===========================================================================
# PgGraphQueryService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_graph_query_exists_and_fetch(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[{"db": "db", "schema": "public", "name": "t1"}],
        columns_data=[], fks_data=[],
    )

    svc = PgGraphQueryService(pool)
    result = await svc.check_graph_data_exists()
    assert result["hasData"] is True
    assert result["nodeCount"] >= 1

    graph = await svc.fetch_graph_data()
    assert len(graph["Nodes"]) >= 1


@pytest.mark.asyncio
async def test_graph_query_cleanup(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[{"db": "db", "schema": "public", "name": "t1"}],
        columns_data=[], fks_data=[],
    )

    svc = PgGraphQueryService(pool)
    await svc.cleanup_graph()
    result = await svc.check_graph_data_exists()
    assert result["hasData"] is False


@pytest.mark.asyncio
async def test_graph_query_related_tables(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[
            {"db": "db", "schema": "public", "name": "orders"},
            {"db": "db", "schema": "public", "name": "customers"},
        ],
        columns_data=[],
        fks_data=[
            {"from_db": "db", "from_schema": "public", "from_table": "orders", "from_column": "cust_id",
             "to_db": "db", "to_schema": "public", "to_table": "customers", "to_column": "id"},
        ],
    )

    svc = PgGraphQueryService(pool)
    result = await svc.fetch_related_tables("orders")
    assert result["base_table"] == "orders"
    assert any(t["name"] == "customers" for t in result["tables"])


# ===========================================================================
# PgGlossaryService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_glossary_crud(pool, clean_db):
    svc = PgGlossaryService(pool)

    created = await svc.create_glossary("Test Glossary", "Desc", "Business")
    gid = int(created["id"])
    assert created["name"] == "Test Glossary"

    glossaries = await svc.fetch_all_glossaries()
    assert len(glossaries["glossaries"]) >= 1

    detail = await svc.fetch_glossary_by_id(gid)
    assert detail["name"] == "Test Glossary"

    await svc.update_glossary(gid, name="Updated Glossary")
    detail = await svc.fetch_glossary_by_id(gid)
    assert detail["name"] == "Updated Glossary"

    await svc.delete_glossary(gid)
    detail = await svc.fetch_glossary_by_id(gid)
    assert detail is None


@pytest.mark.asyncio
async def test_term_crud(pool, clean_db):
    svc = PgGlossaryService(pool)
    created = await svc.create_glossary("G1", "", "Business")
    gid = int(created["id"])

    term_created = await svc.create_term(gid, {"name": "API", "description": "Application Programming Interface"})
    tid = int(term_created["id"])

    terms = await svc.fetch_terms(gid)
    assert len(terms["terms"]) == 1

    detail = await svc.fetch_term_by_id(gid, tid)
    assert detail["name"] == "API"

    await svc.update_term(gid, tid, {"status": "Approved"})
    detail = await svc.fetch_term_by_id(gid, tid)
    assert detail["status"] == "Approved"

    await svc.delete_term(gid, tid)
    terms = await svc.fetch_terms(gid)
    assert len(terms["terms"]) == 0


@pytest.mark.asyncio
async def test_domain_owner_tag(pool, clean_db):
    svc = PgGlossaryService(pool)

    d = await svc.create_domain("Finance", "Financial domain")
    assert d["name"] == "Finance"

    o = await svc.create_owner("John", "john@test.com", "Owner")
    assert o["name"] == "John"

    t = await svc.create_tag("important", "#ff0000")
    assert t["name"] == "important"

    domains = await svc.fetch_all_domains()
    assert len(domains["domains"]) >= 1

    owners = await svc.fetch_all_owners()
    assert len(owners["owners"]) >= 1

    tags = await svc.fetch_all_tags()
    assert len(tags["tags"]) >= 1


# ===========================================================================
# PgSchemaManageService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_schema_manage_tables(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[{"db": "db", "schema": "public", "name": "users", "description": "유저 테이블"}],
        columns_data=[
            {"fqn": "public.users.id", "name": "id", "dtype": "int", "is_primary_key": True,
             "table_db": "db", "table_schema": "public", "table_name": "users"},
        ],
        fks_data=[],
    )

    svc = PgSchemaManageService(pool)
    tables = await svc.fetch_schema_tables(search="users")
    assert len(tables) >= 1
    assert tables[0]["name"] == "users"

    columns = await svc.fetch_table_columns("users")
    assert len(columns) >= 1


@pytest.mark.asyncio
async def test_schema_manage_relationships(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[
            {"db": "db", "schema": "public", "name": "a"},
            {"db": "db", "schema": "public", "name": "b"},
        ],
        columns_data=[], fks_data=[],
    )

    svc = PgSchemaManageService(pool)
    await svc.create_schema_relationship("a", "public", "b_id", "b", "public", "id", "FK_TO_TABLE")

    rels = await svc.fetch_schema_relationships()
    assert any(r["from_table"] == "a" and r["to_table"] == "b" for r in rels)

    await svc.delete_schema_relationship("a", "b_id", "b", "id")
    rels = await svc.fetch_schema_relationships()
    assert not any(r["from_table"] == "a" and r["to_table"] == "b" for r in rels)


@pytest.mark.asyncio
async def test_schema_manage_description_update(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[{"db": "db", "schema": "public", "name": "orders"}],
        columns_data=[
            {"fqn": "public.orders.id", "name": "id", "dtype": "int",
             "table_db": "db", "table_schema": "public", "table_name": "orders"},
        ],
        fks_data=[],
    )

    svc = PgSchemaManageService(pool)
    await svc.update_table_description("orders", "public", "주문 관리 테이블")
    tables = await svc.fetch_schema_tables(search="orders")
    assert tables[0]["description"] == "주문 관리 테이블"

    await svc.update_column_description("orders", "id", "주문 고유 ID")
    columns = await svc.fetch_table_columns("orders", "public")
    assert columns[0]["description"] == "주문 고유 ID"


# ===========================================================================
# PgRelatedTablesService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_related_tables_robo(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[
            {"db": "db", "schema": "public", "name": "orders"},
            {"db": "db", "schema": "public", "name": "items"},
        ],
        columns_data=[],
        fks_data=[
            {"from_db": "db", "from_schema": "public", "from_table": "items", "from_column": "order_id",
             "to_db": "db", "to_schema": "public", "to_table": "orders", "to_column": "id"},
        ],
    )

    svc = PgRelatedTablesService(pool)
    result = await svc.fetch_related_tables_unified({
        "mode": "ROBO", "tableName": "orders", "schemaName": "public",
    })
    assert result["sourceTable"]["tableName"] == "orders"
    assert len(result["relatedTables"]) >= 1


# ===========================================================================
# PgLineageService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_lineage_save_and_fetch(pool, clean_db):
    svc = PgLineageService(pool)
    await svc.save_lineage("etl_proc_1", ["source_db.table_a"], ["target_db.table_b"], "INSERT")

    graph = await svc.fetch_lineage_graph()
    assert len(graph["nodes"]) >= 3
    assert len(graph["edges"]) >= 2
    assert graph["stats"]["etlCount"] >= 1


# ===========================================================================
# PgMetadataService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_metadata_service(pool, clean_db):
    ddl = PgPhaseDDL(pool)
    await ddl.save_ddl_results(
        schemas_data=[{"db": "db", "name": "public"}],
        tables_data=[{"db": "db", "schema": "public", "name": "empty_table"}],
        columns_data=[
            {"fqn": "public.empty_table.col1", "name": "col1", "dtype": "text",
             "table_db": "db", "table_schema": "public", "table_name": "empty_table"},
        ],
        fks_data=[],
    )

    svc = PgMetadataService(pool)
    tables = await svc.get_tables_without_description()
    assert any(t["table_name"] == "empty_table" for t in tables)

    cols = await svc.get_table_columns_info("empty_table", "public")
    assert len(cols) >= 1

    await svc.update_table_description("empty_table", "public", "테스트 테이블")
    tables = await svc.get_tables_without_description()
    assert not any(t["table_name"] == "empty_table" for t in tables)

    fk_set = await svc.get_existing_fk_set()
    assert isinstance(fk_set, set)


# ===========================================================================
# PgBusinessCalendarService 테스트
# ===========================================================================

@pytest.mark.asyncio
async def test_business_calendar_crud(pool, clean_db):
    svc = PgBusinessCalendarService(pool)

    created = await svc.create_calendar("2026 Calendar", "Test", 2026)
    cid = int(created["id"])

    calendars = await svc.fetch_all_calendars()
    assert len(calendars["calendars"]) >= 1

    await svc.add_non_business_day(cid, "2026-01-01", "New Year", "holiday")
    await svc.add_holiday(cid, "2026-12-25", "Christmas", "public")

    detail = await svc.fetch_calendar_by_id(cid)
    assert detail["name"] == "2026 Calendar"
    assert len(detail["nonBusinessDays"]) == 1
    assert len(detail["holidays"]) == 1

    await svc.delete_calendar(cid)
    detail = await svc.fetch_calendar_by_id(cid)
    assert detail is None
