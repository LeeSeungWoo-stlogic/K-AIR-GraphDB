"""
text2sql 서비스 통합 예제 — Neo4j → PostgreSQL+pgvector 전환 가이드.

이 파일은 기존 text2sql/app/main.py, deps.py의 Neo4j 의존성을
PgConnection + 새 모듈로 교체하는 방법을 보여준다.

=== 변경 대상 파일 ===

1) app/deps.py
   - Neo4jConnection 제거 → PgConnection 사용
   - get_neo4j_session → get_pg_connection

2) app/main.py  (lifespan)
   - neo4j_conn.connect() → pg_t2s_conn.connect()
   - ensure_neo4j_schema() → ensure_pg_schema()
   - 각 부트스트랩 함수의 session 인자 → pg_conn 인자

3) app/core/neo4j_bootstrap.py
   - ensure_neo4j_schema() → ensure_pg_schema() 호출로 대체

4) app/core/graph_search.py
   - GraphSearcher(session) → PgGraphSearcher(pg_conn)

5) app/models/neo4j_history.py
   - Neo4jQueryRepository(session) → PgQueryRepository(pg_conn)

6) app/react/tools/neo4j_utils.py
   - 모든 함수의 neo4j_session → pg_conn 인자

7) app/react/tools/build_sql_context_parts/neo4j.py
   - 모든 _neo4j_* 함수 → pg_* 함수로 교체

8) app/config.py
   - neo4j_* 설정 제거, pg_t2s_* 설정 추가 (아래 참조)
"""

# ============================================================
# 1. app/config.py 확장 예시
# ============================================================
CONFIG_EXTENSION = '''
class Settings(BaseSettings):
    # ... 기존 설정 유지 ...

    # --- Neo4j 설정 (제거 대상) ---
    # neo4j_uri: str = "bolt://localhost:7687"
    # neo4j_user: str = "neo4j"
    # neo4j_password: str
    # neo4j_database: str = "neo4j"

    # --- PostgreSQL text2sql 그래프 데이터 설정 (신규) ---
    pg_t2s_host: str = "localhost"
    pg_t2s_port: int = 15432
    pg_t2s_database: str = "age_graph"
    pg_t2s_user: str = "postgres"
    pg_t2s_password: str = "postgres"
    pg_t2s_min_pool: int = 2
    pg_t2s_max_pool: int = 10
'''

# ============================================================
# 2. app/deps.py 교체 예시
# ============================================================
DEPS_REPLACEMENT = '''
from age_graph_repository.text2sql import PgConnection
from app.config import settings

# Neo4jConnection 제거
# neo4j_conn = Neo4jConnection()

# PostgreSQL text2sql 그래프 연결
pg_t2s_conn = PgConnection(
    host=settings.pg_t2s_host,
    port=settings.pg_t2s_port,
    database=settings.pg_t2s_database,
    user=settings.pg_t2s_user,
    password=settings.pg_t2s_password,
    min_size=settings.pg_t2s_min_pool,
    max_size=settings.pg_t2s_max_pool,
)

# FastAPI dependency
async def get_pg_t2s_connection():
    """FastAPI dependency: PgConnection 인스턴스 반환"""
    return pg_t2s_conn
'''

# ============================================================
# 3. app/main.py lifespan 교체 예시
# ============================================================
LIFESPAN_REPLACEMENT = '''
from app.deps import pg_t2s_conn, init_db_pool, close_db_pool
from age_graph_repository.text2sql import ensure_pg_schema

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Text2SQL API (PostgreSQL mode)...")
    await run_startup_sanity_checks_or_raise()

    # PostgreSQL text2sql 그래프 연결
    await pg_t2s_conn.connect()
    print(f"Connected to PostgreSQL text2sql at {settings.pg_t2s_host}:{settings.pg_t2s_port}")

    # DB 커넥션 풀 (타겟 DB용 — 기존 유지)
    await init_db_pool()

    _log_llm_config()

    # PostgreSQL 스키마 부트스트랩
    try:
        result = await ensure_pg_schema(pg_t2s_conn)
        print(f"PG text2sql schema bootstrap: {result}")
    except Exception as e:
        print(f"PG schema bootstrap warning: {e}")

    # ... 나머지 부트스트랩 (text2sql_vectors, validity, enum_cache) ...
    # 이들도 neo4j_session 대신 pg_t2s_conn 을 인자로 전달하도록 수정 필요

    await start_cache_postprocess_workers()

    yield

    # Shutdown
    await stop_text2sql_validity_refresh_task()
    await stop_cache_postprocess_workers()
    await close_db_pool()
    await pg_t2s_conn.close()
    print("Connections closed")
'''

# ============================================================
# 4. build_sql_context 전환 예시
# ============================================================
BUILD_SQL_CONTEXT_REPLACEMENT = '''
# 기존:
from app.react.tools.build_sql_context_parts.neo4j import (
    _neo4j_search_tables_text2sql_vector,
    _neo4j_fetch_fk_neighbors_1hop,
    _neo4j_search_table_scoped_columns,
    ...
)

# 교체:
from age_graph_repository.text2sql import (
    pg_search_tables_text2sql_vector,
    pg_fetch_fk_neighbors_1hop,
    pg_search_table_scoped_columns,
    ...
)

# 호출 변경:
# 기존: candidates, mode = await _neo4j_search_tables_text2sql_vector(context=ctx, ...)
# 교체: candidates, mode = await pg_search_tables_text2sql_vector(pg_conn=pg_t2s_conn, ...)
'''

# ============================================================
# 5. health check 전환
# ============================================================
HEALTH_CHECK = '''
@app.get("/health")
async def health_check():
    try:
        row = await pg_t2s_conn.fetchval("SELECT 1")
        return {
            "status": "healthy",
            "pg_t2s": "connected",
            "config": {
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "target_db": settings.target_db_type,
            }
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
'''

# ============================================================
# 6. 함수 매핑 요약
# ============================================================
FUNCTION_MAPPING = {
    # deps.py
    "Neo4jConnection": "PgConnection",
    "neo4j_conn": "pg_t2s_conn",
    "get_neo4j_session": "get_pg_t2s_connection",

    # neo4j_bootstrap.py
    "ensure_neo4j_schema(session)": "ensure_pg_schema(pg_conn)",

    # graph_search.py
    "GraphSearcher(session)": "PgGraphSearcher(pg_conn)",

    # neo4j_history.py
    "Neo4jQueryRepository(session)": "PgQueryRepository(pg_conn)",
    "save_query(...)": "save_query(...)  # 동일 시그니처",
    "save_value_mapping_by_fqn(...)": "save_value_mapping_by_fqn(...)  # 동일 시그니처",
    "find_similar_queries_by_graph(...)": "find_similar_queries_by_graph(...)  # 동일 시그니처",

    # neo4j_utils.py
    "get_table_importance_scores(neo4j_session)": "get_table_importance_scores(pg_conn)",
    "get_table_fk_relationships(neo4j_session, ...)": "get_table_fk_relationships(pg_conn, ...)",
    "get_table_any_relationships(neo4j_session, ...)": "get_table_any_relationships(pg_conn, ...)",
    "get_column_fk_relationships(neo4j_session, ...)": "get_column_fk_relationships(pg_conn, ...)",

    # build_sql_context_parts/neo4j.py
    "_neo4j_search_tables_text2sql_vector(context=..., ...)": "pg_search_tables_text2sql_vector(pg_conn=..., ...)",
    "_neo4j_fetch_tables_by_names(context=..., ...)": "pg_fetch_tables_by_names(pg_conn=..., ...)",
    "_neo4j_fetch_fk_neighbors_1hop(context=..., ...)": "pg_fetch_fk_neighbors_1hop(pg_conn=..., ...)",
    "_neo4j_search_table_scoped_columns(context=..., ...)": "pg_search_table_scoped_columns(pg_conn=..., ...)",
    "_neo4j_fetch_anchor_like_columns_for_tables(context=..., ...)": "pg_fetch_anchor_like_columns_for_tables(pg_conn=..., ...)",
    "_neo4j_search_columns(context=..., ...)": "pg_search_columns(pg_conn=..., ...)",
    "_neo4j_find_similar_queries_and_mappings(context=..., ...)": "pg_find_similar_queries_and_mappings(pg_conn=..., ...)",
    "_neo4j_fetch_table_schemas(context=..., ...)": "pg_fetch_table_schemas(pg_conn=..., ...)",
    "_neo4j_fetch_fk_relationships(context=..., ...)": "pg_fetch_fk_relationships(pg_conn=..., ...)",
}
