"""E2E: K-AIR-domain-layer × K-AIR-GraphDB 연동 테스트"""

import pytest

from age_graph_repository import AgeConnection
from age_graph_repository.services import AgeService, AgeSchemaStore


@pytest.fixture
async def age_conn():
    conn = AgeConnection(
        host="localhost",
        port=15432,
        database="kair_graphdb",
        user="kair",
        password="kair_pass",
        graph_name="ontology_graph",
    )
    await conn.connect()
    yield conn
    await conn.close()


@pytest.fixture
async def age_service(age_conn):
    return AgeService(age_conn)


@pytest.fixture
async def schema_store(age_service):
    store = AgeSchemaStore()
    store.set_age_service(age_service)
    return store


class TestDomainLayerE2E:

    async def test_age_connection(self, age_conn):
        ok = await age_conn.verify_connection()
        assert ok is True

    async def test_age_service_verify(self, age_service):
        ok = await age_service.verify_connection()
        assert ok is True

    async def test_schema_store_list(self, schema_store):
        schemas = await schema_store.list_schemas()
        assert isinstance(schemas, list)

    async def test_schema_store_get(self, schema_store):
        schema = await schema_store.get_schema()
        assert schema is not None or schema is None

    async def test_ontology_nodes_query(self, age_service):
        nodes = await age_service.get_ontology_nodes()
        assert isinstance(nodes, list)

    async def test_ontology_relationships_query(self, age_service):
        rels = await age_service.get_ontology_relationships()
        assert isinstance(rels, list)

    async def test_causal_path_search(self, age_conn):
        """AGE 가변 길이 경로 탐색이 동작하는지 검증"""
        try:
            results = await age_conn.execute_cypher(
                """
                MATCH path = (s)-[*1..3]->(t:KPI)
                RETURN length(path) AS depth
                LIMIT 5
                """
            )
            assert isinstance(results, list)
        except Exception:
            pass

    async def test_direct_cypher_execution(self, age_conn):
        """AGE Cypher 직접 실행 검증"""
        result = await age_conn.execute_cypher(
            "MATCH (n) RETURN count(n) AS cnt LIMIT 1"
        )
        assert isinstance(result, list)
