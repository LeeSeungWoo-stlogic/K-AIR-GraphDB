"""
text2sql 서비스 Neo4j → PostgreSQL + pgvector 전환 패키지.

Neo4j의 Fabric_Table/Column, T2S_Query/ValueMapping 노드와
HAS_COLUMN, FK_TO, USES_TABLE 등 관계를 asyncpg + pgvector로 대체한다.

포함 모듈:
  - PgConnection: asyncpg 비동기 연결 관리 (text2sql 그래프 데이터용)
  - PgBootstrap: DDL/인덱스 확인 (ensure_neo4j_schema 대체)
  - PgGraphSearcher: pgvector 벡터 검색 (GraphSearcher 대체)
  - PgQueryRepository: 쿼리 캐시/히스토리 (Neo4jQueryRepository 대체)
  - pg_neo4j_utils: FK 관계 유틸 (neo4j_utils.py 대체)
  - pg_context: build_sql_context_parts/neo4j.py 핵심 함수 대체
"""

from .pg_connection import PgConnection
from .pg_bootstrap import ensure_pg_schema
from .pg_graph_search import PgGraphSearcher, TableMatch, ColumnMatch, SubSchema
from .pg_query_repository import PgQueryRepository
from .pg_neo4j_utils import (
    get_table_importance_scores,
    get_table_fk_relationships,
    get_table_any_relationships,
    get_table_relationship_details,
    get_column_fk_relationships,
)
from .pg_context import (
    pg_search_tables_text2sql_vector,
    pg_fetch_tables_by_names,
    pg_fetch_table_embedding_texts,
    pg_fetch_table_embedding_texts_for_tables,
    pg_fetch_fk_neighbors_1hop,
    pg_search_table_scoped_columns,
    pg_fetch_anchor_like_columns_for_tables,
    pg_search_columns,
    pg_find_similar_queries_and_mappings,
    pg_fetch_table_schemas,
    pg_fetch_fk_relationships,
)

__all__ = [
    "PgConnection",
    "ensure_pg_schema",
    "PgGraphSearcher",
    "TableMatch",
    "ColumnMatch",
    "SubSchema",
    "PgQueryRepository",
    "get_table_importance_scores",
    "get_table_fk_relationships",
    "get_table_any_relationships",
    "get_table_relationship_details",
    "get_column_fk_relationships",
    "pg_search_tables_text2sql_vector",
    "pg_fetch_tables_by_names",
    "pg_fetch_table_embedding_texts",
    "pg_fetch_table_embedding_texts_for_tables",
    "pg_fetch_fk_neighbors_1hop",
    "pg_search_table_scoped_columns",
    "pg_fetch_anchor_like_columns_for_tables",
    "pg_search_columns",
    "pg_find_similar_queries_and_mappings",
    "pg_fetch_table_schemas",
    "pg_fetch_fk_relationships",
]
