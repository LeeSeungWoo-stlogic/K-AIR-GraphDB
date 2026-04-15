"""
pgvector 벡터 검색 + Catalog Adapter 통합 테스트.

실행 전 컨테이너 필요:
  docker compose -f docker/age-pgvector/docker-compose.yml up -d
"""

import os
import uuid

import pytest
import pytest_asyncio

from age_graph_repository import AgeConnection, CatalogAdapter, VectorRepository

AGE_HOST = os.getenv("AGE_HOST", "localhost")
AGE_PORT = int(os.getenv("AGE_PORT", "15432"))
AGE_DB = os.getenv("AGE_DB", "kair_graphdb")
AGE_USER = os.getenv("AGE_USER", "kair")
AGE_PASS = os.getenv("AGE_PASS", "kair_pass")

pytestmark = pytest.mark.asyncio

SAMPLE_DIM = 1536


def _random_vec(dim: int = SAMPLE_DIM) -> list[float]:
    """결정적이지만 다양한 테스트 벡터 생성."""
    import hashlib
    seed = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
    vals = []
    for i in range(dim):
        byte_val = int(seed[(i * 2) % len(seed):(i * 2 + 2) % len(seed) or len(seed)], 16)
        vals.append((byte_val - 128) / 256.0)
    return vals


@pytest_asyncio.fixture()
async def conn():
    c = AgeConnection(
        host=AGE_HOST, port=AGE_PORT,
        database=AGE_DB, user=AGE_USER, password=AGE_PASS,
        graph_name="ontology_graph",
        min_pool_size=1, max_pool_size=3,
    )
    await c.connect()
    yield c
    await c.close()


@pytest_asyncio.fixture()
async def vec_repo(conn):
    return VectorRepository(conn)


@pytest_asyncio.fixture()
async def catalog(conn):
    return CatalogAdapter(conn)


# ------------------------------------------------------------------
# VectorRepository: 테이블 임베딩
# ------------------------------------------------------------------

async def test_upsert_and_search_table(vec_repo):
    tid = f"test_tbl_{uuid.uuid4().hex[:8]}"
    vec = _random_vec()

    await vec_repo.upsert_table_embedding(
        table_id=tid,
        dataset_name="WTP_QUALITY",
        embedding=vec,
        description="정수장 수질 데이터",
    )

    results = await vec_repo.search_tables(
        query_embedding=vec, top_k=3,
    )
    assert len(results) > 0
    assert any(r["id"] == tid for r in results)

    await vec_repo.delete_embedding("embedding_tables", tid)


async def test_upsert_and_search_column(vec_repo):
    tid = f"test_tbl_{uuid.uuid4().hex[:8]}"
    cid = f"test_col_{uuid.uuid4().hex[:8]}"
    vec_t = _random_vec()
    vec_c = _random_vec()

    await vec_repo.upsert_table_embedding(tid, "test_table", vec_t)
    await vec_repo.upsert_column_embedding(
        column_id=cid, table_id=tid, column_name="turbidity",
        embedding=vec_c, data_type="float", description="탁도",
    )

    results = await vec_repo.search_columns(
        query_embedding=vec_c, top_k=3,
    )
    assert len(results) > 0
    assert any(r["id"] == cid for r in results)

    await vec_repo.delete_embedding("embedding_columns", cid)
    await vec_repo.delete_embedding("embedding_tables", tid)


async def test_upsert_and_search_query(vec_repo):
    qid = f"test_qry_{uuid.uuid4().hex[:8]}"
    vec = _random_vec()

    await vec_repo.upsert_query_embedding(
        query_id=qid,
        natural_query="정수장 탁도 평균 조회",
        embedding=vec,
        sql_query="SELECT AVG(turbidity) FROM wtp_quality",
    )

    results = await vec_repo.search_similar_queries(
        query_embedding=vec, top_k=3, min_similarity=0.5,
    )
    assert len(results) > 0
    assert any(r["id"] == qid for r in results)

    await vec_repo.delete_embedding("embedding_queries", qid)


async def test_upsert_and_search_ontology_node(vec_repo):
    eid = f"test_onto_{uuid.uuid4().hex[:8]}"
    vec = _random_vec()

    await vec_repo.upsert_ontology_node_embedding(
        embedding_id=eid, node_id="kpi_001",
        embedding=vec, node_name="일평균탁도", node_label="KPI",
        description="정수장 일평균 탁도 KPI",
    )

    results = await vec_repo.search_ontology_nodes(
        query_embedding=vec, top_k=3,
    )
    assert len(results) > 0
    assert any(r["id"] == eid for r in results)

    await vec_repo.delete_embedding("embedding_ontology_nodes", eid)


async def test_count_embeddings(vec_repo):
    cnt = await vec_repo.count_embeddings("embedding_tables")
    assert isinstance(cnt, int)
    assert cnt >= 0


# ------------------------------------------------------------------
# CatalogAdapter: RDB 스키마 동기화
# ------------------------------------------------------------------

async def test_sync_schema_to_rdb(catalog):
    schema = {
        "id": f"test_schema_{uuid.uuid4().hex[:8]}",
        "name": "테스트 스키마",
        "description": "통합 테스트용",
        "domain": "정수장",
        "version": 1,
        "nodes": [],
        "relationships": [],
    }
    await catalog.sync_schema_to_rdb(schema)

    schemas = await catalog.list_schemas()
    assert any(s["id"] == schema["id"] for s in schemas)

    detail = await catalog.get_schema_json(schema["id"])
    assert detail is not None
    assert detail["name"] == "테스트 스키마"

    versions = await catalog.get_schema_versions(schema["id"])
    assert len(versions) >= 1


async def test_schema_version_increment(catalog):
    sid = f"test_ver_{uuid.uuid4().hex[:8]}"
    for v in [1, 2, 3]:
        schema = {
            "id": sid, "name": f"버전 {v}", "description": "",
            "domain": "테스트", "version": v,
        }
        await catalog.sync_schema_to_rdb(schema)

    versions = await catalog.get_schema_versions(sid)
    assert len(versions) == 3
