"""
Phase 2 서비스 통합 테스트 — AgeService, AgeSchemaStore, AgeBehaviorStore, AgeScenarioStore.

age-pgvector 컨테이너 필요:
  docker compose -f docker/age-pgvector/docker-compose.yml up -d
"""

import os
import uuid
from dataclasses import dataclass
from typing import Optional, List

import pytest
import pytest_asyncio

from age_graph_repository import AgeConnection, Labels
from age_graph_repository.services import (
    AgeService, AgeSchemaStore, AgeBehaviorStore, AgeScenarioStore,
)

AGE_HOST = os.getenv("AGE_HOST", "localhost")
AGE_PORT = int(os.getenv("AGE_PORT", "15432"))
AGE_DB = os.getenv("AGE_DB", "kair_graphdb")
AGE_USER = os.getenv("AGE_USER", "kair")
AGE_PASS = os.getenv("AGE_PASS", "kair_pass")

TEST_GRAPH = "test_svc_graph"

pytestmark = pytest.mark.asyncio


@dataclass
class FakeBehavior:
    id: str
    name: str
    behaviorType: str = "Model"
    description: str = ""
    mindsdbModel: str = ""
    modelType: str = ""
    status: str = "pending"
    version: int = 1
    featureViewSQL: str = ""
    metrics: str = "{}"
    trainDataRows: int = 0
    validationSplit: str = ""
    trainedAt: Optional[str] = None


@dataclass
class FakeScenario:
    id: str
    name: str
    schemaId: str
    description: str = ""
    interventions: list = None
    results: dict = None
    traces: list = None
    outputFields: list = None
    createdAt: str = ""
    updatedAt: str = ""

    def __post_init__(self):
        if self.interventions is None:
            self.interventions = []
        if self.traces is None:
            self.traces = []
        if self.outputFields is None:
            self.outputFields = []


@dataclass
class FakeFieldLink:
    id: str
    sourceNodeId: str
    targetNodeId: str
    linkType: str
    field: str
    lag: int = 0
    featureName: str = ""
    importance: float = 0.0
    correlationScore: float = 0.0
    grangerPValue: float = 1.0
    confidence: float = 0.0


@pytest_asyncio.fixture()
async def conn():
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
async def age_svc(conn):
    return AgeService(conn)


@pytest_asyncio.fixture()
async def store(conn):
    svc = AgeService(conn)
    AgeSchemaStore._instance = None
    s = AgeSchemaStore()
    s.set_age_service(svc)
    return s


def _make_schema(**kwargs):
    sid = str(uuid.uuid4())
    return {
        "id": sid,
        "name": kwargs.get("name", "테스트 스키마"),
        "description": "Phase 2 테스트",
        "domain": "정수장",
        "version": 1,
        "nodes": kwargs.get("nodes", []),
        "relationships": kwargs.get("relationships", []),
    }


# ==================================================================
# AgeService tests
# ==================================================================

async def test_age_service_verify(age_svc):
    assert await age_svc.verify_connection()


async def test_age_service_sync_schema(age_svc):
    n1 = {"id": str(uuid.uuid4()), "name": "탁도 KPI", "label": "KPI", "description": "탁도"}
    n2 = {"id": str(uuid.uuid4()), "name": "유입 유량", "label": "Measure", "description": "유입"}
    schema = _make_schema(nodes=[n1, n2])
    await age_svc.sync_ontology_schema(schema)


# ==================================================================
# AgeSchemaStore tests
# ==================================================================

async def test_schema_store_save_and_list(store):
    schema = _make_schema(
        nodes=[
            {"id": str(uuid.uuid4()), "name": "KPI A", "label": "KPI", "description": ""},
            {"id": str(uuid.uuid4()), "name": "Measure B", "label": "Measure", "description": ""},
        ]
    )
    saved = await store.save_schema(schema)
    assert saved["id"] == schema["id"]

    schemas = await store.list_schemas()
    assert any(s["id"] == schema["id"] for s in schemas)


async def test_schema_store_get(store):
    schema = _make_schema()
    await store.save_schema(schema)

    found = await store.get_schema(schema["id"])
    assert found is not None


async def test_schema_store_delete(store):
    schema = _make_schema()
    await store.save_schema(schema)

    ok = await store.delete_schema(schema["id"])
    assert ok is True


async def test_schema_store_active(store):
    schema = _make_schema()
    await store.save_schema(schema)

    active_id = await store.get_active_schema_id()
    assert active_id == schema["id"]


# ==================================================================
# AgeBehaviorStore tests
# ==================================================================

async def test_behavior_save_and_query(store):
    n1_id = str(uuid.uuid4())
    schema = _make_schema(nodes=[
        {"id": n1_id, "name": "Measure X", "label": "Measure", "description": ""},
    ])
    await store.save_schema(schema)

    behavior = FakeBehavior(id=str(uuid.uuid4()), name="predict_turbidity")
    ok = await store.save_behavior_node(schema["id"], behavior)
    assert ok is True

    behaviors = await store.get_behaviors_for_schema(schema["id"])
    assert len(behaviors) >= 1
    assert any(b["modelId"] == behavior.id for b in behaviors)


async def test_behavior_model_graph(store):
    schema = _make_schema(nodes=[
        {"id": str(uuid.uuid4()), "name": "Node A", "label": "Measure", "description": ""},
    ])
    await store.save_schema(schema)

    behavior = FakeBehavior(id=str(uuid.uuid4()), name="model_a")
    await store.save_behavior_node(schema["id"], behavior)

    graph = await store.get_model_graph(schema["id"])
    assert "models" in graph
    assert len(graph["models"]) >= 1


async def test_behavior_update_status(store):
    schema = _make_schema()
    await store.save_schema(schema)

    behavior = FakeBehavior(id=str(uuid.uuid4()), name="status_test")
    await store.save_behavior_node(schema["id"], behavior)

    ok = await store.update_model_status(behavior.id, "trained", '{"rmse": 1.5}')
    assert ok is True


async def test_behavior_delete(store):
    schema = _make_schema()
    await store.save_schema(schema)

    behavior = FakeBehavior(id=str(uuid.uuid4()), name="delete_test")
    await store.save_behavior_node(schema["id"], behavior)

    ok = await store.delete_behavior(behavior.id, schema["id"])
    assert ok is True


# ==================================================================
# AgeScenarioStore tests
# ==================================================================

async def test_scenario_save_and_list(store):
    schema = _make_schema()
    await store.save_schema(schema)

    scenario = FakeScenario(
        id=str(uuid.uuid4()),
        name="테스트 시나리오",
        schemaId=schema["id"],
        interventions=[{"nodeId": "n1", "field": "cost", "value": 100}],
    )
    ok = await store.save_scenario(scenario)
    assert ok is True

    scenarios = await store.list_scenarios(schema["id"])
    assert len(scenarios) >= 1


async def test_scenario_get(store):
    schema = _make_schema()
    await store.save_schema(schema)

    scenario = FakeScenario(
        id=str(uuid.uuid4()), name="상세 조회", schemaId=schema["id"],
    )
    await store.save_scenario(scenario)

    found = await store.get_scenario(scenario.id)
    assert found is not None
    assert found["id"] == scenario.id


async def test_scenario_delete(store):
    schema = _make_schema()
    await store.save_schema(schema)

    scenario = FakeScenario(
        id=str(uuid.uuid4()), name="삭제 테스트", schemaId=schema["id"],
    )
    await store.save_scenario(scenario)

    ok = await store.delete_scenario(scenario.id)
    assert ok is True


async def test_list_all_scenarios(store):
    schema = _make_schema()
    await store.save_schema(schema)

    for i in range(2):
        sc = FakeScenario(
            id=str(uuid.uuid4()), name=f"시나리오 {i}", schemaId=schema["id"],
        )
        await store.save_scenario(sc)

    all_sc = await store.list_all_scenarios()
    assert len(all_sc) >= 2
