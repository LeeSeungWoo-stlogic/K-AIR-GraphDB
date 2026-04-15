"""
Phase 4 통합 예시 — robo-data-analyzer의 main.py / deps.py에 적용하는 방법.

=== 기존 (Neo4j) ===

    # deps.py
    from client.neo4j_client import Neo4jClient
    _neo4j_client = None
    async def get_neo4j_client() -> Neo4jClient:
        global _neo4j_client
        if _neo4j_client is None:
            _neo4j_client = Neo4jClient()
        return _neo4j_client

    # main.py - lifespan
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

=== 전환 후 (PostgreSQL) ===

    # deps.py
    import asyncpg
    from age_graph_repository.analyzer import PgAnalyzerClient

    _pg_pool = None
    _pg_client = None

    async def get_pg_client() -> PgAnalyzerClient:
        global _pg_pool, _pg_client
        if _pg_client is None:
            _pg_pool = await asyncpg.create_pool(
                host=settings.pg.host,       # 기존 NEO4J_URI 대신
                port=settings.pg.port,       # 15432
                user=settings.pg.user,       # kair
                password=settings.pg.password,
                database=settings.pg.database, # kair_graphdb
                min_size=2, max_size=10,
            )
            _pg_client = PgAnalyzerClient(_pg_pool)
        return _pg_client

    async def close_pg_client():
        global _pg_pool, _pg_client
        if _pg_pool:
            await _pg_pool.close()
        _pg_pool = None
        _pg_client = None

    # main.py - lifespan
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await close_pg_client()

=== 서비스 사용 예시 ===

    # graph_query_service.py → PgGraphQueryService
    from age_graph_repository.analyzer import PgGraphQueryService

    svc = PgGraphQueryService(pool)
    result = await svc.check_graph_data_exists()
    graph = await svc.fetch_graph_data()
    await svc.cleanup_graph()

    # phase_ddl.py → PgPhaseDDL
    from age_graph_repository.analyzer import PgPhaseDDL

    ddl = PgPhaseDDL(pool)
    result = await ddl.save_ddl_results(schemas, tables, columns, fks, datasource)

    # glossary_manage_service.py → PgGlossaryService
    from age_graph_repository.analyzer import PgGlossaryService

    glossary_svc = PgGlossaryService(pool)
    glossaries = await glossary_svc.fetch_all_glossaries()
    await glossary_svc.create_glossary("My Glossary", "Description", "Business")

    # schema_manage_service.py → PgSchemaManageService
    from age_graph_repository.analyzer import PgSchemaManageService

    schema_svc = PgSchemaManageService(pool)
    tables = await schema_svc.fetch_schema_tables(search="orders")
    columns = await schema_svc.fetch_table_columns("orders")

    # related_tables_service.py → PgRelatedTablesService
    from age_graph_repository.analyzer import PgRelatedTablesService

    rt_svc = PgRelatedTablesService(pool)
    result = await rt_svc.fetch_related_tables_unified({
        "mode": "ROBO", "tableName": "ORDERS", "schemaName": "public"
    })

    # data_lineage_service.py → PgLineageService
    from age_graph_repository.analyzer import PgLineageService

    lineage_svc = PgLineageService(pool)
    graph = await lineage_svc.fetch_lineage_graph()
    await lineage_svc.save_lineage("proc1", ["src_table"], ["tgt_table"])

    # metadata_enrichment_service.py → PgMetadataService
    from age_graph_repository.analyzer import PgMetadataService

    meta_svc = PgMetadataService(pool)
    tables = await meta_svc.get_tables_without_description()
    await meta_svc.save_fk_relationship({...})

    # business_calendar_service.py → PgBusinessCalendarService
    from age_graph_repository.analyzer import PgBusinessCalendarService

    cal_svc = PgBusinessCalendarService(pool)
    calendars = await cal_svc.fetch_all_calendars()

=== config/settings.py 확장 ===

    class PgConfig(BaseModel):
        host: str = "127.0.0.1"
        port: int = 15432
        user: str = "kair"
        password: str = "kair_pass"
        database: str = "kair_graphdb"

    class AnalyzerConfig(BaseSettings):
        pg: PgConfig = None
        # neo4j: Neo4jConfig = None  # 제거 또는 deprecated
"""
