"""
AGE 통합 테스트 — 실제 age-pgvector 컨테이너에 연결하여 검증.

실행 전 컨테이너 필요:
  docker compose -f docker/age-pgvector/docker-compose.yml up -d

pytest 실행:
  cd libs/age_graph_repository
  python -m pytest tests/test_integration.py -v
"""

import os
import uuid

import pytest
import pytest_asyncio

from age_graph_repository import AgeConnection, AgeGraphRepository, Labels

AGE_HOST = os.getenv("AGE_HOST", "localhost")
AGE_PORT = int(os.getenv("AGE_PORT", "15432"))
AGE_DB = os.getenv("AGE_DB", "kair_graphdb")
AGE_USER = os.getenv("AGE_USER", "kair")
AGE_PASS = os.getenv("AGE_PASS", "kair_pass")

TEST_GRAPH = "test_ontology_graph"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def conn():
    """함수 단위 AGE 연결 (매 테스트마다 새 풀 + 그래프 초기화)."""
    c = AgeConnection(
        host=AGE_HOST, port=AGE_PORT,
        database=AGE_DB, user=AGE_USER, password=AGE_PASS,
        graph_name=TEST_GRAPH,
        min_pool_size=1, max_pool_size=3,
    )
    await c.connect()

    try:
        await c.execute_sql_status(
            f"SELECT * FROM ag_catalog.drop_graph('{TEST_GRAPH}', true);"
        )
    except Exception:
        pass
    await c.execute_sql_status(
        f"SELECT * FROM ag_catalog.create_graph('{TEST_GRAPH}');"
    )

    yield c

    try:
        await c.execute_sql_status(
            f"SELECT * FROM ag_catalog.drop_graph('{TEST_GRAPH}', true);"
        )
    except Exception:
        pass
    await c.close()


@pytest_asyncio.fixture()
async def repo(conn):
    return AgeGraphRepository(conn)


def _make_schema(*, nodes=None, relationships=None):
    """테스트용 OntologySchema dict 생성."""
    sid = str(uuid.uuid4())
    return {
        "id": sid,
        "name": "Test Schema",
        "description": "Integration test schema",
        "domain": "테스트",
        "version": 1,
        "nodes": nodes or [],
        "relationships": relationships or [],
    }


# ------------------------------------------------------------------
# Connection tests
# ------------------------------------------------------------------

async def test_verify_connection(conn):
    assert await conn.verify_connection()


async def test_execute_cypher_return_scalar(conn):
    val = await conn.execute_cypher_scalar("RETURN 1 + 2")
    assert val is not None


# ------------------------------------------------------------------
# Schema sync + query tests
# ------------------------------------------------------------------

async def test_sync_empty_schema(repo):
    schema = _make_schema()
    await repo.sync_ontology_schema(schema)
    nodes = await repo.get_ontology_nodes()
    assert isinstance(nodes, list)


async def test_sync_with_nodes(repo):
    n1 = {"id": str(uuid.uuid4()), "name": "유입 유량", "label": Labels.NODE,
           "description": "정수장 유입 유량", "dataSource": "flow_table"}
    n2 = {"id": str(uuid.uuid4()), "name": "탁도 KPI", "label": Labels.NODE,
           "description": "처리수 탁도", "dataSource": "turbidity_view"}
    schema = _make_schema(nodes=[n1, n2])
    await repo.sync_ontology_schema(schema)

    cnt = await repo.count_nodes(Labels.NODE)
    assert cnt >= 2


async def test_sync_with_relationships(repo):
    n1_id = str(uuid.uuid4())
    n2_id = str(uuid.uuid4())
    n1 = {"id": n1_id, "name": "Process A", "label": Labels.NODE, "description": ""}
    n2 = {"id": n2_id, "name": "Measure B", "label": Labels.NODE, "description": ""}
    r1 = {"id": str(uuid.uuid4()), "source": n1_id, "target": n2_id,
           "type": "PRODUCES", "description": "A produces B"}
    schema = _make_schema(nodes=[n1, n2], relationships=[r1])
    await repo.sync_ontology_schema(schema)

    rels = await repo.get_ontology_relationships()
    assert isinstance(rels, list)


async def test_get_node_by_id(repo):
    node_id = str(uuid.uuid4())
    n = {"id": node_id, "name": "단일 조회 테스트", "label": Labels.NODE, "description": ""}
    schema = _make_schema(nodes=[n])
    await repo.sync_ontology_schema(schema)

    found = await repo.get_node_by_id(node_id)
    assert found is not None


async def test_update_node_properties(repo):
    node_id = str(uuid.uuid4())
    n = {"id": node_id, "name": "업데이트 전", "label": Labels.NODE, "description": ""}
    schema = _make_schema(nodes=[n])
    await repo.sync_ontology_schema(schema)

    ok = await repo.update_node_properties(node_id, {"name": "업데이트 후"})
    assert ok is True


async def test_delete_node(repo):
    node_id = str(uuid.uuid4())
    n = {"id": node_id, "name": "삭제 테스트", "label": Labels.NODE, "description": ""}
    schema = _make_schema(nodes=[n])
    await repo.sync_ontology_schema(schema)

    ok = await repo.delete_node_by_id(node_id)
    assert ok is True

    found = await repo.get_node_by_id(node_id)
    assert found is None


async def test_count_nodes_and_relationships(repo):
    n1_id = str(uuid.uuid4())
    n2_id = str(uuid.uuid4())
    n1 = {"id": n1_id, "name": "Count A", "label": Labels.NODE, "description": ""}
    n2 = {"id": n2_id, "name": "Count B", "label": Labels.NODE, "description": ""}
    r1 = {"id": str(uuid.uuid4()), "source": n1_id, "target": n2_id,
           "type": "MONITORS", "description": ""}
    schema = _make_schema(nodes=[n1, n2], relationships=[r1])
    await repo.sync_ontology_schema(schema)

    nc = await repo.count_nodes()
    rc = await repo.count_relationships()
    assert nc > 0
    assert rc > 0
