"""
domain-layer main.py 통합 예제.

기존 Neo4j 기반 lifespan을 AGE 기반으로 교체하는 패턴을 보여준다.
실제 적용 시 robo-data-domain-layer/app/main.py에 이 패턴을 적용한다.

기존 (Neo4j):
    neo4j_service = Neo4jService()
    await neo4j_service.verify_connection()
    app.state.neo4j = neo4j_service
    schema_store.set_neo4j_service(neo4j_service)

교체 (AGE):
    age_conn = AgeConnection(host=..., port=..., ...)
    await age_conn.connect()
    age_service = AgeService(age_conn)
    await age_service.verify_connection()
    app.state.age = age_service
    schema_store.set_age_service(age_service)

config.py 추가 필드:
    # AGE (Neo4j 대체)
    age_host: str = "localhost"
    age_port: int = 15432
    age_database: str = "kair_graphdb"
    age_user: str = "kair"
    age_password: str = "kair_pass"
    age_graph_name: str = "ontology_graph"
"""

from __future__ import annotations


async def example_age_lifespan():
    """
    main.py lifespan 교체 예시 (실행 불가 — 참조용).

    기존 코드:
    ```python
    # app/main.py (Neo4j)
    from app.services.neo4j_service import Neo4jService

    async with lifespan(app):
        neo4j_service = Neo4jService()
        await neo4j_service.verify_connection()
        app.state.neo4j = neo4j_service
        schema_store = SchemaStore()
        schema_store.set_neo4j_service(neo4j_service)
    ```

    교체 코드:
    ```python
    # app/main.py (AGE)
    from age_graph_repository import AgeConnection
    from age_graph_repository.services import AgeService, AgeSchemaStore

    async with lifespan(app):
        age_conn = AgeConnection(
            host=settings.age_host,
            port=settings.age_port,
            database=settings.age_database,
            user=settings.age_user,
            password=settings.age_password,
            graph_name=settings.age_graph_name,
        )
        await age_conn.connect()

        age_service = AgeService(age_conn)
        connected = await age_service.verify_connection()
        app.state.age = age_service

        schema_store = AgeSchemaStore()
        schema_store.set_age_service(age_service)
        logger.info("AGE 연결 성공" if connected else "AGE 연결 실패")
    ```

    의존성 변경:
    - 제거: neo4j>=5.14.0
    - 추가: asyncpg>=0.29, age-graph-repository (로컬 패키지)

    config.py 추가:
    ```python
    # AGE (Neo4j 대체)
    age_host: str = "localhost"
    age_port: int = 15432
    age_database: str = "kair_graphdb"
    age_user: str = "kair"
    age_password: str = "kair_pass"
    age_graph_name: str = "ontology_graph"
    ```

    health check 변경:
    ```python
    @app.get("/health")
    async def health_check():
        age_status = "connected" if (hasattr(app.state, 'age') and app.state.age) else "disconnected"
        return {"status": "healthy", "service": "domain-layer", "graphdb": age_status}
    ```
    """
    pass


# ================================================================
# 서비스별 import 매핑 참조
# ================================================================
IMPORT_MAPPING = {
    # 기존 (Neo4j)                          # 교체 (AGE)
    "neo4j_service.Neo4jService":           "age_graph_repository.services.AgeService",
    "schema_store.SchemaStore":             "age_graph_repository.services.AgeSchemaStore",
    "schema_store_behavior.BehaviorStore":  "age_graph_repository.services.AgeBehaviorStore",
    "schema_store_scenario.ScenarioStore":  "age_graph_repository.services.AgeScenarioStore",
    "neo4j_guard._requires_neo4j":          "age_graph_repository.services.requires_age",
    "neo4j_labels.Labels":                  "age_graph_repository.Labels",
    "neo4j_labels.LegacyLabels":            "age_graph_repository.LegacyLabels",
}

# ================================================================
# 제거 대상 의존성
# ================================================================
REMOVED_DEPENDENCIES = [
    "neo4j>=5.14.0",
]

ADDED_DEPENDENCIES = [
    "asyncpg>=0.29",
    "age-graph-repository",  # pip install -e libs/age_graph_repository
]
