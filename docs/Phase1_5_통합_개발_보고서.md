# K-AIR-GraphDB 전체 개발 보고서 — Phase 1~5

**작성일**: 2026-04-15  
**기준 문서**: [GraphDB_대체_통합_PRD_v2.md](PRD/GraphDB_대체_통합_PRD_v2.md)  
**인프라**: PostgreSQL 16 + Apache AGE 1.5.0 + pgvector 0.7.4 (Docker)  
**네이밍**: K-AIR-GraphDB (구 age-pgvector)

---

## 1. 총괄 요약

| 항목 | 결과 |
|------|------|
| 완료 Phase | **Phase 1, 2, 3, 4, 5** (전체 완료) |
| 생성 파일 수 | **Python 52개** + **SQL DDL 5개** + **Docker 4개** + **테스트 12개** |
| 라이브러리 테스트 | **94건 전량 PASS** (Phase 1~4 단위·통합) |
| E2E 서비스 테스트 | **26건 전량 PASS** (Phase 5 서비스 래퍼) |
| LLM 통합 테스트 | **9건 전량 PASS** (OpenAI 연동) |
| **전체 테스트** | **129건 전량 PASS** |
| 대체 대상 | Neo4j 전체 (domain-layer, text2sql, analyzer) |
| Neo4j 드라이버 | **제거 가능 상태** (asyncpg 단일 의존) |
| 라이선스 | Apache 2.0 + PostgreSQL License (상업적 완전 자유) |

### 핵심 성과

| Phase | 내용 | 테스트 |
|-------|------|--------|
| Phase 1 | AGE 인프라 + 온톨로지 코어 + 벡터 검색 | 44 PASS |
| Phase 2 | domain-layer 서비스 전환 (4개 서비스) | 14 PASS |
| Phase 3 | text2sql 서비스 전환 (7개 RDB 테이블 + 6개 모듈) | 19 PASS |
| Phase 4 | analyzer 서비스 전환 (25개 RDB 테이블 + 9개 모듈) | 17 PASS |
| Phase 5 | 통합 테스트·서비스 래퍼·LLM 검증·마이그레이션 | 35 PASS (E2E 26 + LLM 9) |

---

## 2. 전체 아키텍처

```
┌────────────────────────────────────────────────────────────────────┐
│                     K-AIR Service Ecosystem                        │
│                                                                    │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐         │
│   │  K-AIR        │  │  K-AIR        │  │  K-AIR        │         │
│   │  domain-layer │  │  text2sql     │  │  analyzer     │         │
│   │  :8002        │  │  :8000        │  │  :5502        │         │
│   │  (FastAPI)    │  │  (FastAPI)    │  │  (FastAPI)    │         │
│   └───────┬───────┘  └───────┬───────┘  └───────┬───────┘         │
│           │                  │                  │                  │
│           └──────────────────┼──────────────────┘                  │
│                              │                                     │
│              ┌───────────────▼───────────────┐                     │
│              │   libs/age_graph_repository   │  ← Python SDK       │
│              │   (asyncpg, 독립 패키지)        │                     │
│              └───────────────┬───────────────┘                     │
│                              │                                     │
│                    ┌─────────▼──────────┐                          │
│                    │   K-AIR-GraphDB    │                          │
│                    │   PostgreSQL 16    │                          │
│                    │   + Apache AGE     │  ← 온톨로지 그래프         │
│                    │   + pgvector       │  ← 벡터 검색 (HNSW)      │
│                    │   :15432           │                          │
│                    └────────────────────┘                          │
│                                                                    │
│   ┌───────────────────────────────────────────────────────────┐   │
│   │               OpenAI LLM API                               │   │
│   │   text-embedding-3-small (임베딩) + gpt-4.1-mini (생성)     │   │
│   └───────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### 데이터 레이어 구조 (K-AIR-GraphDB 내부)

```
PostgreSQL 16 단일 인스턴스
├── Apache AGE 확장          → ontology_graph (Cypher 그래프)
│   └── 5-Layer 온톨로지 노드/관계 (KPI, Measure, Process, Resource, DataSource)
├── pgvector 확장             → HNSW 벡터 인덱스 (코사인 유사도)
├── 온톨로지 RDB 테이블       → ontology_schemas, ontology_schema_versions
├── 임베딩 테이블              → embedding_tables/columns/queries/ontology_nodes
├── text2sql RDB 테이블       → t2s_tables/columns/queries/... (7개)
└── analyzer RDB 테이블       → analyzer_tables/columns/schemas/... (25개)
```

---

## 3. Phase 1: AGE 인프라 + 온톨로지 코어 (PRD 10일)

### 3.1 Docker 인프라

| 파일 | 설명 |
|------|------|
| `docker/K-AIR-GraphDB/Dockerfile` | PostgreSQL 16 + AGE 1.5.0 + pgvector 0.7.4 커스텀 이미지 |
| `docker/K-AIR-GraphDB/docker-compose.yml` | 컨테이너 오케스트레이션 (포트 15432, DB: `kair_graphdb`) |

### 3.2 DDL 초기화 스크립트

| 파일 | PRD ID | 내용 |
|------|--------|------|
| `init/01-extensions.sql` | P1-01 | `CREATE EXTENSION age/vector` + `create_graph('ontology_graph')` |
| `init/02-ontology-tables.sql` | P1-02 | `ontology_schemas` + `ontology_schema_versions` RDB 메타 테이블 |
| `init/03-pgvector-embeddings.sql` | P1-05 | 4개 임베딩 테이블 + HNSW 인덱스 |

### 3.3 코어 Python 모듈 (`libs/age_graph_repository/`)

| 모듈 | PRD ID | 대체 대상 | 설명 |
|------|--------|----------|------|
| `connection.py` | P1-01 | Neo4j Bolt 드라이버 | asyncpg 풀 + Cypher SQL 래핑 |
| `repository.py` | P1-03 | `Neo4jService` CRUD | 노드/관계 CRUD + 경로 탐색 인터페이스 |
| `labels.py` | P1-03 | `neo4j_labels.py` | AGE 단일레이블 상수 (5계층 온톨로지) |
| `cypher_compat.py` | P1-03 | — | Neo4j → AGE Cypher 변환 유틸 (`MERGE` 분해, `agtype` 파싱) |
| `catalog_adapter.py` | P1-04 | — | AGE ↔ Argus Catalog 크로스 쿼리 어댑터 |
| `vector_repository.py` | P1-06 | — | pgvector 벡터 검색 (테이블/컬럼/쿼리/온톨로지 노드) |

### 3.4 Phase 1 테스트 결과

| 테스트 파일 | 건수 | 결과 |
|------------|------|------|
| `test_cypher_compat.py` | 28건 | **28 PASS** |
| `test_integration.py` | 9건 | **9 PASS** |
| `test_vector_repository.py` | 7건 | **7 PASS** |
| **소계** | **44건** | **44 PASS** |

---

## 4. Phase 2: domain-layer 서비스 전환 (PRD 16일)

### 4.1 전환 대상 (원본 → 대체)

| 원본 파일 (domain-layer) | 대체 모듈 | 설명 |
|--------------------------|----------|------|
| `neo4j_service.py` | `services/age_service.py` | 온톨로지 스키마 동기화 + 노드/관계 쿼리 |
| `neo4j_guard.py` | `services/age_guard.py` | `@requires_age` 데코레이터 (연결 보장) |
| `schema_store.py` | `services/age_schema_store.py` | 스키마 CRUD (AGE 그래프 + RDB 이중 저장) |
| `schema_store_behavior.py` | `services/age_behavior_store.py` | 행동 모델 관리 + 필드 링크 |
| `schema_store_scenario.py` | `services/age_scenario_store.py` | What-If 시나리오 프로파일 |
| `main.py` (통합 가이드) | `services/integration_example.py` | lifespan + config 교체 가이드 |

### 4.2 주요 기술 결정

| 결정 사항 | 근거 |
|----------|------|
| AGE Cypher SQL 래핑 | `SELECT * FROM cypher('ontology_graph', $$...$$)` — 모든 Cypher를 Repository 레이어에서 캡슐화 |
| MERGE → INSERT + UPDATE 분리 | AGE의 `MERGE ON CREATE/MATCH SET` 미지원 → `build_merge_as_upsert()` |
| 멀티레이블 → 단일레이블 + `_labels` 속성 | AGE 제약 대응: 가장 구체적 라벨 사용 + 원본 배열 보존 |
| OPTIONAL MATCH → 별도 쿼리 | AGE의 OPTIONAL MATCH 제한 → Python 측 병합 처리 |
| `agtype` 파싱 | `::vertex`/`::edge`/`::path` 접미사 제거 후 JSON 파싱 |
| 레이블 생성 멱등성 | `DuplicateTableError` + `InvalidSchemaNameError` 모두 캐치 |

### 4.3 Phase 2 테스트 결과

| 테스트 파일 | 건수 | 커버리지 |
|------------|------|---------|
| `test_services.py` | 14건 | AgeService, AgeSchemaStore, AgeBehaviorStore, AgeScenarioStore 전 메서드 |
| **소계** | **14건** | **14 PASS** |

---

## 5. Phase 3: text2sql 서비스 전환 (PRD 10일)

### 5.1 아키텍처 결정: Neo4j → 순수 RDB + pgvector

text2sql 서비스는 그래프 경로 탐색이 아닌 **벡터 검색 + FK 조회**가 핵심이므로, Apache AGE 없이 **PostgreSQL RDB + pgvector HNSW**로 직접 전환.

```
기존 (Neo4j):
  :Fabric_Table ─[:HAS_COLUMN]─> :Fabric_Column ─[:FK_TO]─> :Fabric_Column
  :T2S_Query ─[:USES_TABLE]─> :Fabric_Table
  CALL db.index.vector.queryNodes('table_vec_index', k, embedding)

전환 (PostgreSQL + pgvector):
  t2s_tables ─[table_id FK]─> t2s_columns ─[t2s_fk_constraints]─> t2s_columns
  t2s_queries ─[t2s_query_table_usage]─> t2s_tables
  SELECT ... ORDER BY text_to_sql_vector <=> $1::vector LIMIT k
```

### 5.2 DDL 생성

| 파일 | 테이블 수 | 인덱스 수 |
|------|----------|----------|
| `init/04-text2sql-tables.sql` | **7개** | **15개** (HNSW 5개 포함) |

**Neo4j 노드 → RDB 테이블 매핑:**

| Neo4j 요소 | PostgreSQL 대체 | 비고 |
|------------|----------------|------|
| `:Fabric_Table` (12속성) | `t2s_tables` (18컬럼) | `vector` + `text_to_sql_vector` 2개 벡터 컬럼 |
| `:Fabric_Column` (10속성) | `t2s_columns` (14컬럼) | `table_id` FK로 `HAS_COLUMN` 대체 |
| `:FK_TO` 관계 | `t2s_fk_constraints` | `from_column_id` ↔ `to_column_id` |
| `:T2S_Query` (25+속성) | `t2s_queries` (30컬럼) | `vector_question` + `vector_intent` 2개 벡터 |
| `:T2S_ValueMapping` | `t2s_value_mappings` | `column_id` FK + `column_fqn` |
| `:USES_TABLE` 관계 | `t2s_query_table_usage` | 복합 PK (query_id, table_id) |
| `:SELECTS/:FILTERS/...` 관계 | `t2s_query_column_usage` | `usage_type` 컬럼으로 관계 타입 구분 |

### 5.3 Python 모듈 (`libs/age_graph_repository/text2sql/`)

| 모듈 | 대체 대상 | 함수/클래스 수 |
|------|----------|--------------|
| `pg_connection.py` | `Neo4jConnection` | 1 클래스 (7 메서드) |
| `pg_bootstrap.py` | `ensure_neo4j_schema()` | 1 함수 |
| `pg_query_repository.py` | `Neo4jQueryRepository` | 1 클래스 (11 메서드) |
| `pg_graph_search.py` | `GraphSearcher` | 1 클래스 (7 메서드) + 3 dataclass |
| `pg_neo4j_utils.py` | `neo4j_utils.py` (5함수) | 5 함수 |
| `pg_context.py` | `build_sql_context_parts/neo4j.py` (14함수) | 11 함수 + 2 dataclass |

### 5.4 핵심 함수 매핑 (build_sql_context_parts/neo4j.py)

| 원본 Neo4j 함수 | 대체 pgvector+SQL 함수 | 대체 방식 |
|----------------|----------------------|----------|
| `_neo4j_search_tables_text2sql_vector` | `pg_search_tables_text2sql_vector` | `ORDER BY vec <=> $1::vector` (HNSW) |
| `_neo4j_fetch_tables_by_names` | `pg_fetch_tables_by_names` | `SELECT FROM t2s_tables WHERE` |
| `_neo4j_fetch_fk_neighbors_1hop` | `pg_fetch_fk_neighbors_1hop` | 4-way JOIN |
| `_neo4j_search_table_scoped_columns` | `pg_search_table_scoped_columns` | `ROW_NUMBER() OVER (PARTITION BY t.id)` + `<=>` |
| `_neo4j_fetch_anchor_like_columns` | `pg_fetch_anchor_like_columns` | `LIKE '%pattern%'` + `ROW_NUMBER()` |
| `_neo4j_search_columns` | `pg_search_columns` | `ORDER BY c.vector <=> $1::vector` |
| `_neo4j_find_similar_queries_and_mappings` | `pg_find_similar_queries_and_mappings` | 2개 pgvector 쿼리 + VM SQL 조회 |
| `_neo4j_fetch_table_schemas` | `pg_fetch_table_schemas` | `LEFT JOIN` + Python dict 조립 |
| `_neo4j_fetch_fk_relationships` | `pg_fetch_fk_relationships` | 6-way JOIN |

### 5.5 Phase 3 테스트 결과

| 테스트 파일 | 건수 | 커버리지 |
|------------|------|---------|
| `test_text2sql.py` | 19건 | Bootstrap, GraphSearcher, QueryRepository, neo4j_utils, pg_context 전 함수 |
| **소계** | **19건** | **19 PASS** |

---

## 6. Phase 4: analyzer 서비스 전환 (PRD 8일)

### 6.1 아키텍처 결정: Neo4j → 순수 RDB

analyzer 서비스는 DDL 파싱 결과 저장, 메타데이터 관리, 리니지 추적, 용어사전 관리 등을 수행하며, Neo4j의 `Neo4jClient`를 통해 그래프 DB에 CRUD 하는 구조였다. 이를 **PostgreSQL 관계형 테이블 25개**로 전환하여, asyncpg 기반 단일 DB 운영으로 통합한다.

```
기존 (Neo4j):
  :Analyzer_Table ─[:BELONGS_TO]─> :Analyzer_Schema
  :Analyzer_Table ─[:HAS_COLUMN]─> :Analyzer_Column
  :Analyzer_Table ─[:FK_TO_TABLE]─> :Analyzer_Table
  :LineageNode ─[:LINEAGE_EDGE]─> :LineageNode
  :Glossary ─[:HAS_TERM]─> :Term ─[:HAS_DOMAIN/:HAS_OWNER/:HAS_TAG]─> ...
  :BusinessCalendar ─[:HAS_NON_BUSINESS_DAY]─> :NonBusinessDay

전환 (PostgreSQL):
  analyzer_tables ─[schema_name FK]─> analyzer_schemas
  analyzer_tables ─[table_id FK]─> analyzer_columns
  analyzer_table_relationships (from_table_id, to_table_id, rel_type)
  analyzer_lineage_nodes + analyzer_lineage_edges (DAG)
  analyzer_glossaries + analyzer_terms + analyzer_domains/owners/tags (M:N)
  analyzer_business_calendars + analyzer_non_business_days + analyzer_holidays
```

### 6.2 DDL 생성

| 파일 | 테이블 수 | 설명 |
|------|----------|------|
| `init/05-analyzer-tables.sql` | **25개** | analyzer 전체 Neo4j 노드/관계 대체 |

**Neo4j 노드 → RDB 테이블 매핑 (주요):**

| Neo4j 요소 | PostgreSQL 대체 | 비고 |
|------------|----------------|------|
| `:Analyzer_DataSource` 노드 | `analyzer_data_sources` | 데이터소스 메타 |
| `:Analyzer_Schema` 노드 | `analyzer_schemas` + `analyzer_schema_datasource` | M:N 데이터소스 연결 |
| `:Analyzer_Table` 노드 | `analyzer_tables` | `embedding vector(1536)` 포함 |
| `:Analyzer_Column` 노드 | `analyzer_columns` | `table_id` FK |
| `:FK_TO_TABLE` 관계 | `analyzer_table_relationships` | `from_table_id`, `to_table_id`, `rel_type` |
| `:Analyzer_Column_Relationship` | `analyzer_column_relationships` | 컬럼 간 관계 (FK 등) |
| `:Lineage_Node` 노드 | `analyzer_lineage_nodes` | 프로세스/테이블 노드 |
| `:LINEAGE_EDGE` 관계 | `analyzer_lineage_edges` | 리니지 DAG |
| `:Glossary` 노드 | `analyzer_glossaries` | 용어사전 |
| `:Term` 노드 | `analyzer_terms` | 개별 용어 |
| `:Domain` / `:Owner` / `:Tag` | `analyzer_domains` / `analyzer_owners` / `analyzer_tags` | M:N 조인 테이블 |
| `:UserStory` 노드 | `analyzer_user_stories` | 사용자 스토리 |
| `:AST_*` 동적 노드 | `analyzer_ast_nodes` / `analyzer_ast_edges` / `analyzer_ast_table_refs` | SQL AST 파싱 결과 |
| `:ETLProcess` + `:ETL_REF` | `analyzer_etl_table_refs` | ETL 참조 |
| `:BusinessCalendar` | `analyzer_business_calendars` | 영업일 달력 |
| `:NonBusinessDay` / `:Holiday` | `analyzer_non_business_days` / `analyzer_holidays` | 비영업일·공휴일 |

### 6.3 Python 모듈 (`libs/age_graph_repository/analyzer/`)

| 모듈 | 대체 대상 | 핵심 기능 |
|------|----------|----------|
| `pg_analyzer_client.py` | `Neo4jClient` | execute_queries, run_graph_query, batch_unwind, check_nodes_exist |
| `pg_phase_ddl.py` | `phase_ddl.py` (7단계 UNWIND) | 스키마/테이블/컬럼/FK 벌크 INSERT/UPSERT |
| `pg_graph_query_service.py` | `graph_query_service.py` | 그래프 데이터 존재 확인, fetch, cleanup |
| `pg_glossary_service.py` | `glossary_manage_service.py` | 용어사전·용어 CRUD, 도메인/오너/태그 M:N |
| `pg_schema_manage_service.py` | `schema_manage_service.py` | 스키마·테이블 조회, 관계 관리, 설명 업데이트 |
| `pg_related_tables_service.py` | `related_tables_service.py` | FK 기반 관련 테이블 탐색 (ROBO/DATA 모드) |
| `pg_lineage_service.py` | `data_lineage_service.py` | 리니지 노드/엣지 저장 및 DAG 조회 |
| `pg_metadata_service.py` | `metadata_enrichment_service.py` | 미기술 테이블/컬럼 탐색, LLM 설명 저장 |
| `pg_business_calendar_service.py` | `business_calendar_service.py` | 달력/비영업일/공휴일 CRUD |
| `integration_example.py` | — | analyzer 통합 교체 가이드 + 함수 매핑표 |

### 6.4 Phase 4 테스트 결과

| 테스트 파일 | 건수 | 커버리지 |
|------------|------|---------|
| `test_analyzer.py` | 17건 | PgAnalyzerClient, PgPhaseDDL, PgGraphQueryService, PgGlossaryService, PgSchemaManageService, PgRelatedTablesService, PgLineageService, PgMetadataService, PgBusinessCalendarService 전 서비스 |
| **소계** | **17건** | **17 PASS** |

**상세 테스트 항목:**

| # | 테스트 | 검증 내용 |
|---|--------|----------|
| 1 | `test_analyzer_client_execute_queries` | PgAnalyzerClient SQL 실행 + 결과 반환 |
| 2 | `test_analyzer_client_execute_with_params` | 매개변수 바인딩 SQL 실행 |
| 3 | `test_analyzer_client_check_nodes_exist` | EXISTS 쿼리 (테이블 존재 확인) |
| 4 | `test_phase_ddl_save` | 스키마/테이블/컬럼/FK 벌크 저장 (7단계) |
| 5 | `test_graph_query_exists_and_fetch` | 그래프 데이터 존재 확인 + 조회 |
| 6 | `test_graph_query_cleanup` | 데이터소스 기준 cleanup |
| 7 | `test_graph_query_related_tables` | FK 관계 기반 관련 테이블 조회 |
| 8 | `test_glossary_crud` | 용어사전 생성/조회/삭제 |
| 9 | `test_term_crud` | 용어 생성/조회/삭제 |
| 10 | `test_domain_owner_tag` | 도메인·오너·태그 M:N 연결 |
| 11 | `test_schema_manage_tables` | 스키마별 테이블 목록 조회 |
| 12 | `test_schema_manage_relationships` | 테이블 간 관계 저장/조회 |
| 13 | `test_schema_manage_description_update` | 테이블 설명 업데이트 |
| 14 | `test_related_tables_robo` | ROBO 모드 관련 테이블 탐색 |
| 15 | `test_lineage_save_and_fetch` | 리니지 노드/엣지 저장 및 DAG 조회 |
| 16 | `test_metadata_service` | 미기술 테이블 탐색 + 설명 저장 |
| 17 | `test_business_calendar_crud` | 달력·비영업일·공휴일 CRUD |

---

## 7. Phase 5: 통합 테스트·안정화·마이그레이션 (PRD 9일)

### 7.1 핵심 요청사항 반영

| # | 요청사항 | 반영 결과 |
|---|---------|----------|
| 1 | Git 브런치/업로드 미진행 | 로컬 파일 시스템 기반 개발 |
| 2 | B 방안 (신규 서비스 래퍼) 채택 | `services/` 디렉터리에 3개 독립 서비스 생성 |
| 3 | age-pgvector → K-AIR-GraphDB 네이밍 통일 | Docker, 설정, 문서 전체 적용 |
| 4 | robo-data-* → K-AIR-* 네이밍 전환 | 서비스명·컨테이너명·API 제목 모두 적용 |

### 7.2 네이밍 전환 (P5-00)

| 변경 전 | 변경 후 |
|---------|---------|
| `docker/age-pgvector/` | `docker/K-AIR-GraphDB/` |
| 컨테이너 `age-pgvector` | 컨테이너 `kair-graphdb` |
| 볼륨 `age_data` | 볼륨 `kair_graphdb_data` |
| `robo-data-domain-layer` | `K-AIR-domain-layer` |
| `robo-data-text2sql` | `K-AIR-text2sql` |
| `robo-data-analyzer` | `K-AIR-analyzer` |

### 7.3 서비스 래퍼 구현 (B 방안)

기존 K-AIR 코드(`repos/KAIR/`)를 직접 수정하지 않고, 동일 API 구조를 가진 신규 서비스를 `services/` 디렉터리에 생성하여 Neo4j 의존성을 K-AIR-GraphDB로 교체.

#### K-AIR-domain-layer (`services/K-AIR-domain-layer/`)
| 파일 | 역할 |
|------|------|
| `app/config.py` | GraphDBConfig (AGE 연결 설정) |
| `app/deps.py` | AgeConnection + AgeService + AgeSchemaStore 주입 |
| `app/main.py` | FastAPI lifespan (AGE 연결/해제) |
| `app/routers/ontology.py` | 스키마·노드·관계·인과분석·탐색 라우터 |

#### K-AIR-text2sql (`services/K-AIR-text2sql/`)
| 파일 | 역할 |
|------|------|
| `app/config.py` | GraphDBConfig + TargetDBConfig |
| `app/deps.py` | PgConnection(t2s) + 대상DB 풀 |
| `app/main.py` | FastAPI lifespan |
| `app/routers/text2sql.py` | 테이블 조회·벡터 검색·FK 관계·쿼리 이력 |

#### K-AIR-analyzer (`services/K-AIR-analyzer/`)
| 파일 | 역할 |
|------|------|
| `app/config.py` | GraphDBConfig + LLM/병렬처리 설정 |
| `app/deps.py` | PgAnalyzerClient + 10개 서비스 팩토리 |
| `app/main.py` | FastAPI lifespan |
| `app/routers/analysis.py` | 그래프 조회·스키마·관련 테이블·리니지·메타데이터 |
| `app/routers/glossary.py` | 용어사전·영업일 달력 CRUD |

### 7.4 E2E 통합 테스트

3개 서비스 × K-AIR-GraphDB 실제 연동 테스트.

```
========== 26 passed in 12.18s ==========

services/tests/test_e2e_domain_layer.py   8 tests  ✅ ALL PASSED
services/tests/test_e2e_text2sql.py       7 tests  ✅ ALL PASSED
services/tests/test_e2e_analyzer.py      11 tests  ✅ ALL PASSED
```

| 서비스 | 건수 | 주요 테스트 항목 |
|--------|------|-----------------|
| domain-layer | 8건 | AGE 연결, AgeService 가동, 스키마 조회, 온톨로지 노드/관계 Cypher, 가변 길이 경로 탐색 |
| text2sql | 7건 | PgConnection 연결, DDL 부트스트랩, 테이블/컬럼 CRUD, 쿼리 이력 CRUD |
| analyzer | 11건 | PgAnalyzerClient SQL, PgPhaseDDL 벌크 저장, 용어사전/달력 CRUD, 리니지, 메타데이터 |

### 7.5 LLM 통합 테스트

K-AIR-GraphDB + OpenAI API 연동 검증 (별도 상세 보고서: [LLM_통합_테스트_보고서.md](LLM_통합_테스트_보고서.md)).

```
======================== 9 passed in 12.73s ========================
```

| 테스트 클래스 | 건수 | 검증 내용 |
|-------------|------|----------|
| `TestLLMConnection` | 2 | OpenAI API 키 유효성, 임베딩 모델 가용성 (1536차원) |
| `TestEmbeddingPgvector` | 3 | 임베딩 생성→pgvector 저장→시맨틱 검색 (Top-K 정확성) |
| `TestLLMGeneration` | 3 | 테이블 설명 생성, 자연어→SQL, 온톨로지 개념 추출 |
| `TestLLMCleanup` | 1 | 테스트 데이터 정리 |

**주요 검증 결과:**
- pgvector 시맨틱 검색: "주문 금액과 결제 정보" → orders(Top-1), payments(Top-2) 정확 반환
- 자연어→SQL: JOIN/GROUP BY/HAVING/date_trunc 포함 PostgreSQL 쿼리 생성 성공
- 온톨로지 추출: K-Water 수처리 문서 → 5-Layer 온톨로지 개념 정확 추출

### 7.6 데이터 마이그레이션 스크립트

`scripts/migrate_neo4j_to_kair_graphdb.py` — 통합 마이그레이션 엔트리포인트:

| Phase | 대상 | 옵션 |
|-------|------|------|
| Phase A | AGE 온톨로지 그래프 (기존 `migrate_neo4j_to_age.py` 호출) | `--graph-only` |
| Phase B | 관계형 테이블 (t2s_*/analyzer_* 적재) | `--tables-only` |
| (기본) | 전체 마이그레이션 | — |

### 7.7 Docker Compose 통합 구성

`docker/K-AIR-GraphDB/docker-compose.full.yml` — 4개 서비스 통합:

| 서비스 | 포트 | 의존성 |
|--------|------|--------|
| kair-graphdb | 15432 | — |
| kair-domain-layer | 8002 | kair-graphdb (healthy) |
| kair-text2sql | 8000 | kair-graphdb (healthy) |
| kair-analyzer | 5502 | kair-graphdb (healthy) |

### 7.8 AGE Cypher 호환성 버그 수정

E2E 테스트 중 발견된 AGE Cypher 예약어 충돌 수정:

| 위치 | 문제 | 수정 |
|------|------|------|
| `age_service.py:get_ontology_nodes` | `AS desc` → AGE 예약어 충돌 | `AS node_desc` + return_cols 명시 |
| `age_service.py:get_ontology_relationships` | `AS desc` → 동일 | `AS rel_desc` + return_cols 명시 |

---

## 8. 전체 테스트 결과

### 8.1 Phase별 집계

| Phase | 테스트 파일 | 건수 | 상태 |
|-------|------------|------|------|
| Phase 1 | `test_cypher_compat.py` | 28 | PASS |
| Phase 1 | `test_integration.py` | 9 | PASS |
| Phase 1 | `test_vector_repository.py` | 7 | PASS |
| Phase 2 | `test_services.py` | 14 | PASS |
| Phase 3 | `test_text2sql.py` | 19 | PASS |
| Phase 4 | `test_analyzer.py` | 17 | PASS |
| Phase 5 E2E | `test_e2e_domain_layer.py` | 8 | PASS |
| Phase 5 E2E | `test_e2e_text2sql.py` | 7 | PASS |
| Phase 5 E2E | `test_e2e_analyzer.py` | 11 | PASS |
| Phase 5 LLM | `test_e2e_llm_integration.py` | 9 | PASS |
| **합계** | | **129건** | **전량 PASS** |

### 8.2 테스트 유형별 분류

| 유형 | 건수 | 설명 |
|------|------|------|
| 단위 테스트 (Unit) | 28 | Cypher 호환성 변환 로직 |
| 라이브러리 통합 테스트 | 66 | AGE/pgvector/analyzer 실제 DB 연동 (P1~P4) |
| 서비스 E2E 테스트 | 26 | FastAPI 서비스 래퍼 × K-AIR-GraphDB |
| LLM 통합 테스트 | 9 | OpenAI API × pgvector × K-AIR-GraphDB |
| **합계** | **129** | |

---

## 9. Neo4j → K-AIR-GraphDB 전환 매핑 (전체)

### 9.1 domain-layer

| 기존 (Neo4j) | 전환 후 (K-AIR-GraphDB) |
|---|---|
| `Neo4jService` | `AgeConnection` + `AgeService` |
| `SchemaStore.set_neo4j_service()` | `AgeSchemaStore.set_age_service()` |
| `BehaviorStore` | `AgeBehaviorStore` |
| `ScenarioStore` | `AgeScenarioStore` |
| `neo4j_guard` → `@requires_neo4j` | `age_guard` → `@requires_age` |

### 9.2 text2sql

| 기존 (Neo4j) | 전환 후 (K-AIR-GraphDB) |
|---|---|
| `Neo4jConnection` | `PgConnection` |
| `ensure_neo4j_schema()` | `PgBootstrap.ensure_schema()` |
| `Neo4jQueryRepository` | `PgQueryRepository` |
| `GraphSearcher` | `PgGraphSearcher` |
| `neo4j_utils.py` (5함수) | `pg_neo4j_utils.py` (5함수) |
| `build_sql_context_parts/neo4j.py` (14함수) | `pg_context.py` (11함수) |

### 9.3 analyzer

| 기존 (Neo4j) | 전환 후 (K-AIR-GraphDB) |
|---|---|
| `Neo4jClient` | `PgAnalyzerClient` |
| `phase_ddl.py` (7단계 UNWIND) | `PgPhaseDDL` (SQL UPSERT) |
| `graph_query_service` | `PgGraphQueryService` |
| `glossary_manage_service` | `PgGlossaryService` |
| `schema_manage_service` | `PgSchemaManageService` |
| `related_tables_service` | `PgRelatedTablesService` |
| `data_lineage_service` | `PgLineageService` |
| `metadata_enrichment_service` | `PgMetadataService` |
| `business_calendar_service` | `PgBusinessCalendarService` |

---

## 10. AGE 기술 제약 대응 현황

| AGE 제약 | 대응 방안 | 구현 상태 |
|---------|----------|----------|
| 멀티레이블 미지원 | `_labels` 속성에 원본 배열 JSON 보존 | ✅ `repository.py`, `age_service.py` |
| `MERGE ON CREATE/MATCH SET` 제한 | `build_merge_as_upsert()` → 존재 확인 후 CREATE/SET 분리 | ✅ `cypher_compat.py` |
| OPTIONAL MATCH 제한 | 별도 쿼리 후 Python 측 병합 | ✅ `age_schema_store.py` |
| SQL 래핑 필수 | `AgeConnection.execute_cypher()` 캡슐화 | ✅ `connection.py` |
| `CALL` 프로시저 미지원 | 벡터 검색은 pgvector SQL 분리 | ✅ `pg_context.py` |
| `agtype` 반환 형식 | `parse_agtype()` → 접미사 제거 후 JSON 파싱 | ✅ `cypher_compat.py` |
| 레이블 중복 생성 오류 | `DuplicateTableError` + `InvalidSchemaNameError` 캐치 | ✅ `connection.py` |
| Cypher 예약어 충돌 (`desc`) | `AS node_desc` / `AS rel_desc` 별칭 사용 | ✅ `age_service.py` |

---

## 11. 성능 특성

### 11.1 pgvector HNSW vs Neo4j 벡터 인덱스

| 항목 | Neo4j `db.index.vector.queryNodes` | pgvector HNSW `<=>` |
|------|-----------------------------------|---------------------|
| 인덱스 유형 | 내장 벡터 인덱스 | HNSW (m=16, ef_construction=200) |
| 유사도 함수 | cosine | cosine (`vector_cosine_ops`) |
| 필터링 | 인덱스 내 WHERE | SQL WHERE (post-filter) |
| 동일 트랜잭션 JOIN | 불가 (별도 DB) | **가능** (동일 PostgreSQL) |

### 11.2 FK 관계 조회

| 항목 | Neo4j Cypher | PostgreSQL SQL |
|------|-------------|----------------|
| 1-hop FK | `MATCH -[:HAS_COLUMN]-[:FK_TO]-[:HAS_COLUMN]-` | 4-way JOIN |
| 가변 경로 [*1..3] | Cypher 내장 | CTE 또는 반복 쿼리 |
| 인덱스 | 관계 타입별 자동 | `t2s_fk_constraints` / `analyzer_table_relationships` 양방향 인덱스 |

---

## 12. 산출물 전체 목록

### 12.1 Docker / DDL

| 파일 | Phase | 설명 |
|------|-------|------|
| `docker/K-AIR-GraphDB/Dockerfile` | 0 | PostgreSQL 16 + AGE 1.5.0 + pgvector 0.7.4 |
| `docker/K-AIR-GraphDB/docker-compose.yml` | 0 | 단독 실행 (port 15432) |
| `docker/K-AIR-GraphDB/docker-compose.full.yml` | 5 | 4개 서비스 통합 |
| `docker/K-AIR-GraphDB/init/01-extensions.sql` | 1 | 확장 설치 + 그래프 생성 |
| `docker/K-AIR-GraphDB/init/02-ontology-tables.sql` | 1 | 온톨로지 스키마 메타 테이블 |
| `docker/K-AIR-GraphDB/init/03-pgvector-embeddings.sql` | 1 | 4개 임베딩 테이블 + HNSW |
| `docker/K-AIR-GraphDB/init/04-text2sql-tables.sql` | 3 | 7개 text2sql 테이블 + HNSW 5개 |
| `docker/K-AIR-GraphDB/init/05-analyzer-tables.sql` | 4 | 25개 analyzer 테이블 |

### 12.2 코어 라이브러리 — `libs/age_graph_repository/`

| 파일 | Phase | 역할 |
|------|-------|------|
| `__init__.py` | 1 | 패키지 초기화 + export |
| `connection.py` | 1 | asyncpg + AGE Cypher 래퍼 |
| `repository.py` | 1 | 온톨로지 그래프 CRUD |
| `labels.py` | 1 | AGE vertex/edge 레이블 상수 |
| `cypher_compat.py` | 1 | Neo4j → AGE Cypher 변환 |
| `catalog_adapter.py` | 1 | Argus Catalog 크로스 쿼리 |
| `vector_repository.py` | 1 | pgvector 벡터 검색 모듈 |
| `pyproject.toml` | 1 | Python 패키지 메타데이터 |
| `services/age_service.py` | 2 | Neo4jService drop-in 대체 |
| `services/age_guard.py` | 2 | @requires_age 데코레이터 |
| `services/age_schema_store.py` | 2 | SchemaStore AGE 전환 |
| `services/age_behavior_store.py` | 2 | BehaviorStore AGE 전환 |
| `services/age_scenario_store.py` | 2 | ScenarioStore AGE 전환 |
| `services/integration_example.py` | 2 | domain-layer 통합 가이드 |
| `text2sql/pg_connection.py` | 3 | asyncpg 풀 (Neo4jConnection 대체) |
| `text2sql/pg_bootstrap.py` | 3 | ensure_neo4j_schema 대체 |
| `text2sql/pg_query_repository.py` | 3 | Neo4jQueryRepository 대체 |
| `text2sql/pg_graph_search.py` | 3 | GraphSearcher 대체 |
| `text2sql/pg_neo4j_utils.py` | 3 | neo4j_utils.py 대체 |
| `text2sql/pg_context.py` | 3 | build_sql_context_parts/neo4j.py 대체 |
| `text2sql/integration_example.py` | 3 | text2sql 통합 가이드 |
| `analyzer/pg_analyzer_client.py` | 4 | Neo4jClient drop-in 대체 |
| `analyzer/pg_phase_ddl.py` | 4 | phase_ddl 7단계 UNWIND → SQL UPSERT |
| `analyzer/pg_graph_query_service.py` | 4 | 그래프 데이터 존재/조회/cleanup |
| `analyzer/pg_glossary_service.py` | 4 | 용어사전·용어 CRUD |
| `analyzer/pg_schema_manage_service.py` | 4 | 스키마·테이블 관리 |
| `analyzer/pg_related_tables_service.py` | 4 | FK 기반 관련 테이블 탐색 |
| `analyzer/pg_lineage_service.py` | 4 | 리니지 DAG 저장/조회 |
| `analyzer/pg_metadata_service.py` | 4 | 미기술 테이블 탐색·LLM 설명 저장 |
| `analyzer/pg_business_calendar_service.py` | 4 | 영업일 달력 CRUD |
| `analyzer/integration_example.py` | 4 | analyzer 통합 교체 가이드 |

### 12.3 서비스 래퍼 — `services/`

| 파일 | Phase | 역할 |
|------|-------|------|
| `K-AIR-domain-layer/app/main.py` | 5 | FastAPI 앱 진입점 |
| `K-AIR-domain-layer/app/config.py` | 5 | 환경 설정 |
| `K-AIR-domain-layer/app/deps.py` | 5 | 의존성 주입 |
| `K-AIR-domain-layer/app/routers/ontology.py` | 5 | 온톨로지 API |
| `K-AIR-domain-layer/requirements.txt` | 5 | 의존 패키지 |
| `K-AIR-text2sql/app/main.py` | 5 | FastAPI 앱 진입점 |
| `K-AIR-text2sql/app/config.py` | 5 | 환경 설정 |
| `K-AIR-text2sql/app/deps.py` | 5 | 의존성 주입 |
| `K-AIR-text2sql/app/routers/text2sql.py` | 5 | Text2SQL API |
| `K-AIR-text2sql/requirements.txt` | 5 | 의존 패키지 |
| `K-AIR-analyzer/app/main.py` | 5 | FastAPI 앱 진입점 |
| `K-AIR-analyzer/app/config.py` | 5 | 환경 설정 |
| `K-AIR-analyzer/app/deps.py` | 5 | 의존성 주입 |
| `K-AIR-analyzer/app/routers/analysis.py` | 5 | 분석 API |
| `K-AIR-analyzer/app/routers/glossary.py` | 5 | 용어사전 API |
| `K-AIR-analyzer/requirements.txt` | 5 | 의존 패키지 |

### 12.4 테스트

| 파일 | Phase | 건수 |
|------|-------|------|
| `libs/age_graph_repository/tests/test_cypher_compat.py` | 1 | 28 |
| `libs/age_graph_repository/tests/test_integration.py` | 1 | 9 |
| `libs/age_graph_repository/tests/test_vector_repository.py` | 1 | 7 |
| `libs/age_graph_repository/tests/test_services.py` | 2 | 14 |
| `libs/age_graph_repository/tests/test_text2sql.py` | 3 | 19 |
| `libs/age_graph_repository/tests/test_analyzer.py` | 4 | 17 |
| `services/tests/test_e2e_domain_layer.py` | 5 | 8 |
| `services/tests/test_e2e_text2sql.py` | 5 | 7 |
| `services/tests/test_e2e_analyzer.py` | 5 | 11 |
| `services/tests/test_e2e_llm_integration.py` | 5 | 9 |
| **합계** | | **129** |

### 12.5 스크립트

| 파일 | Phase | 역할 |
|------|-------|------|
| `scripts/export_neo4j.py` | — | Neo4j 데이터 JSON 덤프 |
| `scripts/migrate_neo4j_to_age.py` | — | Neo4j → AGE 그래프 마이그레이션 |
| `scripts/migrate_neo4j_to_kair_graphdb.py` | 5 | 통합 마이그레이션 (그래프 + 관계형 테이블) |

---

## 13. 기존 repos 코드와의 관계

### 13.1 수정된 파일: 없음

Phase 1~5 전체에서 `repos/KAIR/` 하위의 기존 코드는 **일절 수정하지 않았다.** 모든 신규 코드는 다음 위치에 독립 배치되었다:

- `libs/age_graph_repository/` — 코어 라이브러리 (Phase 1~4)
- `services/K-AIR-*/` — 서비스 래퍼 (Phase 5)
- `docker/K-AIR-GraphDB/` — 인프라 (전 Phase)

### 13.2 연동 방식: B 방안 (서비스 래퍼)

| 방안 | 설명 | 채택 |
|------|------|------|
| A 방안 | 기존 repos 코드에 직접 Neo4j→AGE import 교체 | — |
| **B 방안** | **신규 서비스 래퍼 생성 (기존 코드 무수정)** | **✅ 채택** |

B 방안의 장점:
- 기존 K-AIR 코드 무수정 → 롤백 리스크 제로
- 독립 배포·테스트 가능 → MSA 원칙 준수
- 점진적 전환 가능 → 트래픽 분기 후 검증

---

## 14. 디렉토리 구조 (전체)

```
K_Water_v1/
├── docker/
│   ├── K-AIR-GraphDB/                 ← PostgreSQL + AGE + pgvector (인프라)
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml         ← 단독 실행
│   │   ├── docker-compose.full.yml    ← 4개 서비스 통합
│   │   └── init/
│   │       ├── 01-extensions.sql      ← Phase 1
│   │       ├── 02-ontology-tables.sql ← Phase 1
│   │       ├── 03-pgvector-embeddings.sql ← Phase 1
│   │       ├── 04-text2sql-tables.sql ← Phase 3
│   │       └── 05-analyzer-tables.sql ← Phase 4
│   └── age-pgvector/                  ← 구 네이밍 (보존)
│
├── libs/
│   └── age_graph_repository/          ← SDK (Phase 1~4)
│       ├── __init__.py
│       ├── connection.py              ← AGE asyncpg 연결
│       ├── repository.py              ← 온톨로지 CRUD
│       ├── labels.py                  ← 레이블 상수
│       ├── cypher_compat.py           ← Cypher 변환
│       ├── catalog_adapter.py         ← Argus 연동
│       ├── vector_repository.py       ← pgvector 검색
│       ├── pyproject.toml
│       │
│       ├── services/                  ← Phase 2: domain-layer
│       │   ├── age_service.py
│       │   ├── age_guard.py
│       │   ├── age_schema_store.py
│       │   ├── age_behavior_store.py
│       │   ├── age_scenario_store.py
│       │   └── integration_example.py
│       │
│       ├── text2sql/                  ← Phase 3: text2sql
│       │   ├── pg_connection.py
│       │   ├── pg_bootstrap.py
│       │   ├── pg_query_repository.py
│       │   ├── pg_graph_search.py
│       │   ├── pg_neo4j_utils.py
│       │   ├── pg_context.py
│       │   └── integration_example.py
│       │
│       ├── analyzer/                  ← Phase 4: analyzer
│       │   ├── pg_analyzer_client.py
│       │   ├── pg_phase_ddl.py
│       │   ├── pg_graph_query_service.py
│       │   ├── pg_glossary_service.py
│       │   ├── pg_schema_manage_service.py
│       │   ├── pg_related_tables_service.py
│       │   ├── pg_lineage_service.py
│       │   ├── pg_metadata_service.py
│       │   ├── pg_business_calendar_service.py
│       │   └── integration_example.py
│       │
│       └── tests/                     ← 라이브러리 테스트 (94건)
│           ├── test_cypher_compat.py   (28건)
│           ├── test_integration.py     (9건)
│           ├── test_vector_repository.py (7건)
│           ├── test_services.py        (14건)
│           ├── test_text2sql.py        (19건)
│           └── test_analyzer.py        (17건)
│
├── services/                          ← Phase 5: 서비스 래퍼
│   ├── K-AIR-domain-layer/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── deps.py
│   │   │   └── routers/ontology.py
│   │   └── requirements.txt
│   ├── K-AIR-text2sql/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── deps.py
│   │   │   └── routers/text2sql.py
│   │   └── requirements.txt
│   ├── K-AIR-analyzer/
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── deps.py
│   │   │   └── routers/
│   │   │       ├── analysis.py
│   │   │       └── glossary.py
│   │   └── requirements.txt
│   └── tests/                         ← E2E + LLM 테스트 (35건)
│       ├── conftest.py
│       ├── pytest.ini
│       ├── test_e2e_domain_layer.py    (8건)
│       ├── test_e2e_text2sql.py        (7건)
│       ├── test_e2e_analyzer.py        (11건)
│       └── test_e2e_llm_integration.py (9건)
│
├── scripts/
│   ├── export_neo4j.py
│   ├── migrate_neo4j_to_age.py
│   └── migrate_neo4j_to_kair_graphdb.py  ← 통합 마이그레이션
│
├── repos/KAIR/                        ← 기존 코드 (수정 없음)
│   ├── robo-data-domain-layer/
│   ├── robo-data-text2sql/
│   └── robo-data-platform/
│
└── docs/
    ├── PRD/GraphDB_대체_통합_PRD_v2.md
    ├── GraphDB_마이그레이션_검증_보고서.md
    ├── Phase1_3_개발_보고서.md          ← 기존 (Phase 1~3)
    ├── Phase5_개발_보고서.md            ← 기존 (Phase 5)
    ├── LLM_통합_테스트_보고서.md          ← LLM 테스트 결과
    └── Phase1_5_통합_개발_보고서.md      ← 본 문서 (전체 통합)
```

---

## 15. 결론

1. **Phase 1 (인프라)**: PostgreSQL + AGE + pgvector Docker 환경 구축 완료. 온톨로지 그래프 CRUD, Argus Catalog 크로스 쿼리, pgvector 벡터 검색 모듈이 **44개 테스트**로 검증됨.

2. **Phase 2 (domain-layer)**: `Neo4jService`, `SchemaStore`, `BehaviorStore`, `ScenarioStore` 4개 핵심 서비스의 AGE 호환 drop-in 대체 모듈이 **14개 테스트**로 검증됨.

3. **Phase 3 (text2sql)**: Neo4j 의존 전체 41개 파일 분석 후, 7개 RDB 테이블 + 15개 인덱스 DDL과 6개 Python 모듈로 전환 완료. **19개 테스트**로 검증됨.

4. **Phase 4 (analyzer)**: `Neo4jClient` 포함 9개 서비스 모듈을 PostgreSQL 25개 테이블 기반으로 전환. DDL 벌크 저장, 용어사전, 리니지, 메타데이터 보강 등 **17개 테스트**로 검증됨.

5. **Phase 5 (통합·안정화)**: B 방안(서비스 래퍼)으로 3개 K-AIR 서비스 독립 구현. E2E **26건** + LLM 통합 **9건** = **35개 테스트** 전량 PASS. 데이터 마이그레이션 스크립트 및 Docker Compose 통합 구성 완료.

6. **기존 코드 무수정**: `repos/KAIR/` 하위 코드는 일절 수정하지 않았으며, 독립 패키지(`libs/`) + 서비스 래퍼(`services/`)로 개발하여 롤백 리스크를 제거함.

7. **전체 129개 테스트 PASS**: AGE 그래프 연결부터 pgvector 벡터 검색, LLM 기반 시맨틱 검색·SQL 생성·온톨로지 추출까지 모든 핵심 기능이 실제 Docker 컨테이너 + OpenAI API 대상으로 검증됨.

**Phase 1~5 전체 개발이 성공적으로 완료되었습니다.**

---

## 16. 향후 고려사항

| # | 항목 | 우선순위 | 비고 |
|---|------|---------|------|
| 1 | 각 서비스 Dockerfile 작성 | 높음 | Docker Compose 통합 실행 가능화 |
| 2 | 성능 벤치마크 (100K+ rows) | 중간 | pgvector HNSW 대용량 검색 성능 측정 |
| 3 | 프로덕션 환경 설정 | 높음 | SSL, 시크릿 관리, 커넥션 풀 튜닝 |
| 4 | CI/CD 파이프라인 | 중간 | 자동 테스트·빌드·배포 |
| 5 | 실 데이터 마이그레이션 | 높음 | 화성정수장 Neo4j 데이터 → K-AIR-GraphDB 이관 |
| 6 | A/B 트래픽 분기 | 낮음 | 기존 Neo4j 서비스 vs 신규 K-AIR-GraphDB 서비스 비교 운영 |
