"""
text2sql 전환 모듈 통합 테스트.

age-pgvector Docker 컨테이너가 실행 중이어야 한다:
  docker compose -f docker/age-pgvector/docker-compose.yml up -d

실행:
  cd libs/age_graph_repository
  python -m pytest tests/test_text2sql.py -v
"""

import os
import sys
import asyncio
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from text2sql.pg_connection import PgConnection
from text2sql.pg_bootstrap import ensure_pg_schema
from text2sql.pg_graph_search import PgGraphSearcher, format_subschema_for_prompt
from text2sql.pg_query_repository import PgQueryRepository
from text2sql.pg_neo4j_utils import (
    get_table_importance_scores,
    get_table_fk_relationships,
    get_table_relationship_details,
    get_column_fk_relationships,
)
from text2sql.pg_context import (
    pg_search_tables_text2sql_vector,
    pg_fetch_tables_by_names,
    pg_fetch_fk_neighbors_1hop,
    pg_search_columns,
    pg_find_similar_queries_and_mappings,
    pg_fetch_table_schemas,
    pg_fetch_fk_relationships,
)

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "15432"))
PG_DB = os.getenv("PG_DB", "kair_graphdb")
PG_USER = os.getenv("PG_USER", "kair")
PG_PASS = os.getenv("PG_PASS", "kair_pass")


@pytest_asyncio.fixture(scope="function")
async def pg_conn():
    conn = PgConnection(
        host=PG_HOST, port=PG_PORT,
        database=PG_DB, user=PG_USER, password=PG_PASS,
    )
    await conn.connect()
    yield conn
    await conn.close()


SAMPLE_VEC = [0.01] * 1536


# ──────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap(pg_conn: PgConnection):
    result = await ensure_pg_schema(pg_conn)
    assert result["ok"] is True
    assert result["tables_checked"] == 7


# ──────────────────────────────────────────────────────────────
# Seed data
# ──────────────────────────────────────────────────────────────

async def _seed_data(pg_conn: PgConnection):
    """테스트용 샘플 데이터 삽입."""
    vec_str = "[" + ",".join("0.01" for _ in range(1536)) + "]"

    await pg_conn.execute("DELETE FROM t2s_value_mappings")
    await pg_conn.execute("DELETE FROM t2s_query_column_usage")
    await pg_conn.execute("DELETE FROM t2s_query_table_usage")
    await pg_conn.execute("DELETE FROM t2s_queries")
    await pg_conn.execute("DELETE FROM t2s_fk_constraints")
    await pg_conn.execute("DELETE FROM t2s_columns")
    await pg_conn.execute("DELETE FROM t2s_tables")

    await pg_conn.execute(
        """
        INSERT INTO t2s_tables (db, schema_name, name, description, analyzed_description,
                                vector, text_to_sql_vector, text_to_sql_embedding_text)
        VALUES
          ('postgresql', 'public', 'wtp_quality', '수질 데이터', '정수장 수질 측정',
           $1::vector, $1::vector, '수질 측정 테이블'),
          ('postgresql', 'public', 'wtp_facility', '시설 데이터', '정수장 시설 정보',
           $1::vector, $1::vector, '시설 정보 테이블'),
          ('postgresql', 'public', 'code_master', '코드 마스터', '코드 관리',
           $1::vector, $1::vector, '코드 마스터 테이블')
        ON CONFLICT (db, schema_name, name) DO NOTHING
        """,
        vec_str,
    )

    t_quality = await pg_conn.fetchval(
        "SELECT id FROM t2s_tables WHERE name = 'wtp_quality'"
    )
    t_facility = await pg_conn.fetchval(
        "SELECT id FROM t2s_tables WHERE name = 'wtp_facility'"
    )
    t_code = await pg_conn.fetchval(
        "SELECT id FROM t2s_tables WHERE name = 'code_master'"
    )

    await pg_conn.execute(
        """
        INSERT INTO t2s_columns (table_id, name, fqn, dtype, description, vector)
        VALUES
          ($1, 'facility_id', 'public.wtp_quality.facility_id', 'varchar', '시설 ID', $4::vector),
          ($1, 'turbidity', 'public.wtp_quality.turbidity', 'float', '탁도', $4::vector),
          ($1, 'measure_date', 'public.wtp_quality.measure_date', 'date', '측정일', $4::vector),
          ($2, 'id', 'public.wtp_facility.id', 'varchar', '시설 PK', $4::vector),
          ($2, 'name', 'public.wtp_facility.name', 'varchar', '시설명', $4::vector),
          ($2, 'code_id', 'public.wtp_facility.code_id', 'varchar', '코드 참조', $4::vector),
          ($3, 'id', 'public.code_master.id', 'varchar', '코드 PK', $4::vector),
          ($3, 'code_name', 'public.code_master.code_name', 'varchar', '코드명', $4::vector)
        ON CONFLICT (fqn) DO NOTHING
        """,
        t_quality, t_facility, t_code, vec_str,
    )

    c_facility_id = await pg_conn.fetchval(
        "SELECT id FROM t2s_columns WHERE fqn = 'public.wtp_quality.facility_id'"
    )
    c_facility_pk = await pg_conn.fetchval(
        "SELECT id FROM t2s_columns WHERE fqn = 'public.wtp_facility.id'"
    )
    c_code_id = await pg_conn.fetchval(
        "SELECT id FROM t2s_columns WHERE fqn = 'public.wtp_facility.code_id'"
    )
    c_code_pk = await pg_conn.fetchval(
        "SELECT id FROM t2s_columns WHERE fqn = 'public.code_master.id'"
    )

    if c_facility_id and c_facility_pk:
        await pg_conn.execute(
            """
            INSERT INTO t2s_fk_constraints (from_column_id, to_column_id, constraint_name)
            VALUES ($1, $2, 'fk_quality_facility')
            ON CONFLICT DO NOTHING
            """,
            c_facility_id, c_facility_pk,
        )
    if c_code_id and c_code_pk:
        await pg_conn.execute(
            """
            INSERT INTO t2s_fk_constraints (from_column_id, to_column_id, constraint_name)
            VALUES ($1, $2, 'fk_facility_code')
            ON CONFLICT DO NOTHING
            """,
            c_code_id, c_code_pk,
        )


@pytest.mark.asyncio
async def test_seed_data(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    count = await pg_conn.fetchval("SELECT count(*) FROM t2s_tables")
    assert count >= 3


# ──────────────────────────────────────────────────────────────
# PgGraphSearcher
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_searcher_search_tables(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    gs = PgGraphSearcher(pg_conn, top_k=5)
    matches = await gs.search_tables(SAMPLE_VEC, k=3)
    assert len(matches) >= 1
    assert matches[0].name in ("wtp_quality", "wtp_facility", "code_master")


@pytest.mark.asyncio
async def test_graph_searcher_search_columns(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    gs = PgGraphSearcher(pg_conn)
    matches = await gs.search_columns(SAMPLE_VEC, k=5)
    assert len(matches) >= 1


@pytest.mark.asyncio
async def test_graph_searcher_fk_details(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    gs = PgGraphSearcher(pg_conn)
    keys = [
        {"db": "postgresql", "schema": "public", "name": "wtp_quality"},
        {"db": "postgresql", "schema": "public", "name": "wtp_facility"},
    ]
    details = await gs.get_fk_details(keys)
    assert len(details) >= 1
    assert details[0]["from_column"] == "facility_id"


@pytest.mark.asyncio
async def test_graph_searcher_build_subschema(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    gs = PgGraphSearcher(pg_conn, top_k=3)
    sub = await gs.build_subschema(SAMPLE_VEC, top_k_tables=3, top_k_columns=5)
    assert len(sub.tables) >= 1
    text = format_subschema_for_prompt(sub)
    assert "Available Tables" in text


# ──────────────────────────────────────────────────────────────
# PgQueryRepository
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_repository_save_and_get(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    repo = PgQueryRepository(pg_conn)

    qid = await repo.save_query(
        question="화성정수장 평균 탁도",
        sql="SELECT avg(turbidity) FROM wtp_quality",
        status="completed",
        row_count=1,
        execution_time_ms=120.5,
        steps_count=3,
        db="postgresql",
        react_caching_db_type="postgresql",
    )
    assert qid

    history = await repo.get_query_history(page=1, page_size=10)
    assert history["total"] >= 1

    deleted = await repo.delete_query(qid)
    assert deleted is True


@pytest.mark.asyncio
async def test_query_repository_value_mapping(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    repo = PgQueryRepository(pg_conn)

    await repo.save_value_mapping_by_fqn(
        natural_value="화성정수장",
        code_value="WTP001",
        column_fqn="public.wtp_quality.facility_id",
    )

    mappings = await repo.find_value_mapping("화성정수장")
    assert len(mappings) >= 1
    assert mappings[0]["code_value"] == "WTP001"


# ──────────────────────────────────────────────────────────────
# neo4j_utils 대체
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_table_importance_scores(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    scores = await get_table_importance_scores(pg_conn)
    assert "wtp_quality" in scores or "wtp_facility" in scores


@pytest.mark.asyncio
async def test_table_fk_relationships(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    rels = await get_table_fk_relationships(pg_conn, "wtp_quality", limit=10)
    assert len(rels) >= 1
    assert rels[0]["related_table"] == "wtp_facility"


@pytest.mark.asyncio
async def test_table_relationship_details(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    details = await get_table_relationship_details(pg_conn, "wtp_quality", relation_limit=10)
    assert "fk_relationships" in details
    assert len(details["fk_relationships"]) >= 1


@pytest.mark.asyncio
async def test_column_fk_relationships(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    rels = await get_column_fk_relationships(
        pg_conn, "wtp_quality", "facility_id", limit=5
    )
    assert len(rels) >= 1
    assert rels[0]["referenced_table"] == "wtp_facility"


# ──────────────────────────────────────────────────────────────
# pg_context 함수
# ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pg_search_tables_text2sql_vector(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    candidates, mode = await pg_search_tables_text2sql_vector(
        pg_conn=pg_conn, embedding=SAMPLE_VEC, k=3
    )
    assert mode == "pgvector_hnsw"
    assert len(candidates) >= 1


@pytest.mark.asyncio
async def test_pg_fetch_tables_by_names(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    tables = await pg_fetch_tables_by_names(
        pg_conn=pg_conn, names=["wtp_quality", "nonexistent"], schema=None
    )
    assert len(tables) >= 1
    assert tables[0].name == "wtp_quality"


@pytest.mark.asyncio
async def test_pg_fetch_fk_neighbors(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    neighbors = await pg_fetch_fk_neighbors_1hop(
        pg_conn=pg_conn,
        seed_fqns=["public.wtp_quality"],
        schema=None,
        limit=10,
    )
    assert len(neighbors) >= 1
    assert neighbors[0].name == "wtp_facility"


@pytest.mark.asyncio
async def test_pg_search_columns(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    cols = await pg_search_columns(pg_conn=pg_conn, embedding=SAMPLE_VEC, k=5)
    assert len(cols) >= 1


@pytest.mark.asyncio
async def test_pg_fetch_table_schemas(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    from text2sql.pg_context import TableCandidate
    tables = [TableCandidate(name="wtp_quality")]
    schemas = await pg_fetch_table_schemas(pg_conn=pg_conn, tables=tables)
    assert len(schemas) >= 1
    assert schemas[0]["name"] == "wtp_quality"
    assert len(schemas[0]["columns"]) >= 1


@pytest.mark.asyncio
async def test_pg_fetch_fk_relationships(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    fks = await pg_fetch_fk_relationships(
        pg_conn=pg_conn,
        table_fqns=["public.wtp_quality", "public.wtp_facility"],
    )
    assert len(fks) >= 1


@pytest.mark.asyncio
async def test_pg_similar_queries(pg_conn: PgConnection):
    await _seed_data(pg_conn)
    repo = PgQueryRepository(pg_conn)

    qid = await repo.save_query(
        question="평균 탁도 조회",
        sql="SELECT avg(turbidity) FROM wtp_quality",
        status="completed",
        row_count=1,
        verified=True,
        db="postgresql",
        react_caching_db_type="postgresql",
    )

    await pg_conn.execute(
        "UPDATE t2s_queries SET vector_question = $1::vector WHERE id = $2",
        "[" + ",".join("0.01" for _ in range(1536)) + "]",
        qid,
    )

    similar, mappings = await pg_find_similar_queries_and_mappings(
        pg_conn=pg_conn,
        question="탁도 평균",
        question_embedding=SAMPLE_VEC,
        terms=["화성정수장"],
        min_similarity=0.0,
        use_verified_only=True,
    )
    assert len(similar) >= 1
    assert similar[0]["sql"] is not None

    await repo.delete_query(qid)
