# K-AIR-GraphDB

**Neo4j → PostgreSQL (Apache AGE + pgvector) 전환 프로젝트**

K-AIR 솔루션의 GraphDB 의존성을 상용 라이선스 기반 Neo4j에서 오픈소스 PostgreSQL 생태계로 완전 전환하는 프로젝트입니다.

---

## 프로젝트 배경

K-AIR 솔루션은 온톨로지 그래프 관리(domain-layer), 자연어→SQL 변환(text2sql), 데이터 분석 자동화(analyzer) 3개 핵심 서비스가 Neo4j에 의존하고 있었습니다. 라이선스 비용과 운영 복잡성을 해소하기 위해 **PostgreSQL 단일 인스턴스**에 Apache AGE(그래프)와 pgvector(벡터 검색)를 결합한 대체 아키텍처를 설계·구현했습니다.

## 아키텍처

```
┌───────────────────────────────────────────────────────────┐
│                  K-AIR Service Ecosystem                   │
│                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ K-AIR       │  │ K-AIR       │  │ K-AIR       │       │
│  │ domain-layer│  │ text2sql    │  │ analyzer    │       │
│  │ :8002       │  │ :8000       │  │ :5502       │       │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘       │
│         └────────────────┼────────────────┘               │
│                          │                                │
│            ┌─────────────▼─────────────┐                  │
│            │  libs/age_graph_repository │ ← Python SDK     │
│            └─────────────┬─────────────┘                  │
│                          │                                │
│                ┌─────────▼─────────┐                      │
│                │  K-AIR-GraphDB    │                      │
│                │  PostgreSQL 16    │                      │
│                │  + Apache AGE     │ ← 온톨로지 그래프     │
│                │  + pgvector       │ ← 벡터 검색 (HNSW)   │
│                │  :15432           │                      │
│                └───────────────────┘                      │
└───────────────────────────────────────────────────────────┘
```

### 데이터 레이어 (K-AIR-GraphDB 내부)

| 확장/영역 | 용도 | 테이블/그래프 |
|-----------|------|-------------|
| Apache AGE | 5-Layer 온톨로지 그래프 (Cypher) | `ontology_graph` |
| pgvector | HNSW 코사인 유사도 검색 | `embedding_*`, `t2s_*.vector` |
| RDB 테이블 | text2sql 메타데이터 | `t2s_tables/columns/queries` 등 7개 |
| RDB 테이블 | analyzer 메타데이터 | `analyzer_tables/columns/schemas` 등 25개 |

## 디렉터리 구조

```
K-AIR-GraphDB/
├── docker/
│   ├── K-AIR-GraphDB/                 ← PostgreSQL + AGE + pgvector Docker
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml         ← 단독 실행
│   │   ├── docker-compose.full.yml    ← 서비스 4종 통합 실행
│   │   └── init/                      ← DDL 초기화 스크립트 (5개)
│   └── age-pgvector/                  ← 원본 네이밍 (참고용)
│
├── libs/age_graph_repository/         ← 코어 Python 라이브러리
│   ├── connection.py                  ← asyncpg + AGE Cypher 래퍼
│   ├── repository.py                  ← 온톨로지 그래프 CRUD
│   ├── cypher_compat.py               ← Neo4j → AGE Cypher 변환
│   ├── vector_repository.py           ← pgvector 벡터 검색
│   ├── services/                      ← domain-layer 전환 모듈 (Phase 2)
│   ├── text2sql/                      ← text2sql 전환 모듈 (Phase 3)
│   ├── analyzer/                      ← analyzer 전환 모듈 (Phase 4)
│   └── tests/                         ← 라이브러리 단위·통합 테스트 (94건)
│
├── services/                          ← FastAPI 서비스 래퍼 (Phase 5)
│   ├── K-AIR-domain-layer/            ← 온톨로지 관리 API
│   ├── K-AIR-text2sql/                ← 자연어→SQL 변환 API
│   ├── K-AIR-analyzer/                ← 데이터 분석 자동화 API
│   └── tests/                         ← E2E + LLM 통합 테스트 (35건)
│
├── scripts/                           ← 마이그레이션 스크립트
│   ├── export_neo4j.py                ← Neo4j 데이터 JSON 덤프
│   ├── migrate_neo4j_to_age.py        ← Neo4j → AGE 그래프 마이그레이션
│   ├── migrate_neo4j_to_kair_graphdb.py ← 통합 마이그레이션 (그래프+RDB)
│   └── verify_migration.py            ← 마이그레이션 검증
│
└── docs/                              ← 보고서
    ├── PRD/                           ← 제품 요구사항 정의서 (GraphDB 전환)
    ├── Phase1_5_통합_개발_보고서.md     ← 전체 Phase 통합 보고서
    ├── LLM_통합_테스트_보고서.md        ← OpenAI 연동 테스트 결과
    └── GraphDB_마이그레이션_검증_보고서.md
```

## 개발 Phase

| Phase | 내용 | 테스트 | 상태 |
|-------|------|--------|------|
| **Phase 1** | AGE 인프라 + 온톨로지 코어 + 벡터 검색 | 44 PASS | ✅ |
| **Phase 2** | domain-layer 서비스 전환 (4개 모듈) | 14 PASS | ✅ |
| **Phase 3** | text2sql 서비스 전환 (7 RDB + 6 모듈) | 19 PASS | ✅ |
| **Phase 4** | analyzer 서비스 전환 (25 RDB + 9 모듈) | 17 PASS | ✅ |
| **Phase 5** | 통합 테스트 · 서비스 래퍼 · LLM 검증 | 35 PASS | ✅ |
| | **합계** | **129 PASS** | |

## 빠른 시작

### 1. K-AIR-GraphDB 실행

```bash
cd docker/K-AIR-GraphDB
docker compose up -d
```

PostgreSQL 16 + AGE + pgvector가 `localhost:15432`에서 실행됩니다.

- **DB**: `kair_graphdb`
- **User**: `kair`
- **Password**: `kair_secure_2024`

### 2. 라이브러리 설치

```bash
cd libs/age_graph_repository
pip install -e .
```

### 3. 테스트 실행

```bash
# 라이브러리 테스트 (94건)
cd libs/age_graph_repository
PYTHONPATH=../.. pytest tests/ -v --override-ini="asyncio_mode=auto"

# E2E 서비스 테스트 (26건)
cd services/tests
PYTHONPATH=../../libs pytest -v --override-ini="asyncio_mode=auto"

# LLM 통합 테스트 (9건, OpenAI API 키 필요)
OPENAI_API_KEY=sk-... pytest test_e2e_llm_integration.py -v --override-ini="asyncio_mode=auto"
```

### 4. 서비스 통합 실행 (Docker Compose)

```bash
cd docker/K-AIR-GraphDB
docker compose -f docker-compose.full.yml up -d
```

## Neo4j → K-AIR-GraphDB 전환 매핑

### domain-layer

| Neo4j (기존) | K-AIR-GraphDB (전환) |
|---|---|
| `Neo4jService` | `AgeService` |
| `SchemaStore` | `AgeSchemaStore` |
| `BehaviorStore` | `AgeBehaviorStore` |
| `neo4j.AsyncGraphDatabase` | `asyncpg.create_pool()` |

### text2sql

| Neo4j (기존) | K-AIR-GraphDB (전환) |
|---|---|
| `Neo4jConnection` | `PgConnection` |
| `GraphSearcher` | `PgGraphSearcher` |
| `db.index.vector.queryNodes()` | `ORDER BY vec <=> $1::vector` (HNSW) |
| `MATCH -[:FK_TO]-` | 4~6 way SQL JOIN |

### analyzer

| Neo4j (기존) | K-AIR-GraphDB (전환) |
|---|---|
| `Neo4jClient` | `PgAnalyzerClient` |
| `phase_ddl.py` (UNWIND) | `PgPhaseDDL` (SQL UPSERT) |
| `glossary_manage_service` | `PgGlossaryService` |
| `data_lineage_service` | `PgLineageService` |
| `metadata_enrichment_service` | `PgMetadataService` |

## 기술 스택

| 기술 | 버전 | 용도 |
|------|------|------|
| PostgreSQL | 16 | 통합 데이터베이스 |
| Apache AGE | 1.5.0 | 그래프 쿼리 (Cypher) |
| pgvector | 0.7.4 | 벡터 검색 (HNSW) |
| Python | 3.11+ | 서비스 및 라이브러리 |
| asyncpg | latest | 비동기 PostgreSQL 드라이버 |
| FastAPI | latest | 서비스 래퍼 프레임워크 |
| OpenAI API | gpt-4.1-mini / text-embedding-3-small | LLM 및 임베딩 |

## 라이선스

- **Apache AGE**: Apache License 2.0
- **pgvector**: PostgreSQL License
- **PostgreSQL**: PostgreSQL License

모두 상업적 사용에 제한 없는 오픈소스 라이선스입니다.
