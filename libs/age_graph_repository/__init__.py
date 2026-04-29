"""
Apache AGE Graph Repository — Neo4j neo4j_service.py 대체 모듈.

K-AIR domain-layer의 Neo4jService와 동일한 인터페이스를 제공하되,
백엔드를 PostgreSQL + Apache AGE로 교체한다.

포함 모듈:
  - physical_meta: AGE 물리 계층(Table/Column/FK_TO) 속성 계약·빌더
  - AgeConnection: asyncpg 비동기 연결 관리
  - AgeGraphRepository: 온톨로지 그래프 CRUD + 경로 탐색
  - CatalogAdapter: Argus Catalog 연동 (AGE ↔ RDB 크로스 쿼리)
  - VectorRepository: pgvector 벡터 검색 (HNSW 코사인 유사도)
  - cypher_compat: Neo4j → AGE Cypher 호환성 변환
  - Labels: AGE vertex/edge label 상수
"""

from .connection import AgeConnection
from .repository import AgeGraphRepository
from .catalog_adapter import CatalogAdapter
from .vector_repository import VectorRepository
from .labels import Labels, LegacyLabels
from .cypher_compat import (
    escape_cypher_value,
    build_properties_clause,
    neo4j_to_age_cypher,
    build_merge_as_upsert,
    parse_agtype,
)

__all__ = [
    "AgeConnection",
    "AgeGraphRepository",
    "CatalogAdapter",
    "VectorRepository",
    "Labels",
    "LegacyLabels",
    "escape_cypher_value",
    "build_properties_clause",
    "neo4j_to_age_cypher",
    "build_merge_as_upsert",
    "parse_agtype",
]
