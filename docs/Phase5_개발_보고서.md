# Phase 5 개발 보고서 — 통합 테스트·안정화·마이그레이션

**작성일**: 2026-04-14  
**버전**: v1.0

---

## 1. 개요

Phase 5는 PRD v2의 최종 단계로, 이전 Phase 1~4에서 개발한 K-AIR-GraphDB(PostgreSQL + Apache AGE + pgvector) 기반 서비스들을 통합하여 E2E 검증을 수행하고, 실제 배포 가능한 형태로 안정화하는 단계이다.

### 핵심 요청사항 반영
| # | 요청사항 | 반영 결과 |
|---|---------|----------|
| 1 | Git 브런치/업로드 미진행 | 로컬 파일 시스템 기반 개발 |
| 2 | B 방안 (신규 서비스 래퍼) 채택 | `services/` 디렉터리에 3개 독립 서비스 생성 |
| 3 | age-pgvector → K-AIR-GraphDB 네이밍 통일 | Docker, 설정, 문서 전체 적용 |
| 4 | robo-data-* → K-AIR-* 네이밍 전환 | 서비스명·컨테이너명·API 제목 모두 적용 |

---

## 2. 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│                    K-AIR Service Ecosystem                    │
│                                                              │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐      │
│  │  K-AIR        │ │  K-AIR        │ │  K-AIR        │      │
│  │  domain-layer │ │  text2sql     │ │  analyzer     │      │
│  │  :8002        │ │  :8000        │ │  :5502        │      │
│  └───────┬───────┘ └───────┬───────┘ └───────┬───────┘      │
│          │                 │                 │               │
│          └─────────────────┼─────────────────┘               │
│                            │                                 │
│                    ┌───────▼───────┐                         │
│                    │  K-AIR-GraphDB │                        │
│                    │  PostgreSQL 16 │                        │
│                    │  + Apache AGE  │                        │
│                    │  + pgvector    │                        │
│                    │  :15432        │                        │
│                    └───────────────┘                         │
│                                                              │
│  SDK: libs/age_graph_repository (Python asyncpg)             │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 작업 내역

### 3.1 네이밍 전환 (P5-00)

| 변경 전 | 변경 후 |
|---------|---------|
| `docker/age-pgvector/` | `docker/K-AIR-GraphDB/` |
| 컨테이너 `age-pgvector` | 컨테이너 `kair-graphdb` |
| 볼륨 `age_data` | 볼륨 `kair_graphdb_data` |
| `robo-data-domain-layer` | `K-AIR-domain-layer` |
| `robo-data-text2sql` | `K-AIR-text2sql` |
| `robo-data-analyzer` | `K-AIR-analyzer` |

### 3.2 서비스 래퍼 구현 (P5-01 ~ P5-04)

**B 방안**: 기존 K-AIR 코드를 직접 수정하지 않고, 동일 API 구조를 가진 신규 서비스를 생성하여 Neo4j 의존성을 K-AIR-GraphDB로 교체.

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

### 3.3 E2E 통합 테스트 (P5-05)

3개 서비스 × K-AIR-GraphDB 실제 연동 테스트.

```
========== 26 passed in 12.18s ==========

services/tests/test_e2e_domain_layer.py   8 tests  ✅ ALL PASSED
services/tests/test_e2e_text2sql.py       7 tests  ✅ ALL PASSED
services/tests/test_e2e_analyzer.py      11 tests  ✅ ALL PASSED
```

#### 주요 테스트 항목

**Domain Layer (8건)**
- AGE 연결/인증 검증
- AgeService 가동 확인
- AgeSchemaStore 스키마 목록/상세 조회
- 온톨로지 노드/관계 Cypher 조회
- AGE 가변 길이 경로 탐색 (인과 분석)
- Cypher 직접 실행

**Text2SQL (7건)**
- PgConnection 연결 검증
- DDL 스키마 부트스트랩
- t2s_* 테이블 존재 확인 (5개 이상)
- 테이블/컬럼 CRUD (UPSERT)
- 쿼리 이력 CRUD
- E2E 데이터 정리

**Analyzer (11건)**
- PgAnalyzerClient SQL 실행
- analyzer_* 테이블 존재 확인 (15개 이상)
- PgPhaseDDL 벌크 저장
- PgGraphQueryService 존재 확인
- PgGlossaryService 용어사전 CRUD
- PgSchemaManageService 테이블 조회
- PgRelatedTablesService 관련 테이블 (ROBO 모드)
- PgLineageService 리니지 저장/조회
- PgMetadataService 미기술 테이블 탐색
- PgBusinessCalendarService 달력 CRUD
- E2E 데이터 정리

### 3.4 AGE Cypher 호환성 버그 수정

E2E 테스트 중 발견된 AGE Cypher 예약어 충돌 수정:

| 위치 | 문제 | 수정 |
|------|------|------|
| `age_service.py:get_ontology_nodes` | `AS desc` → AGE 예약어 충돌 | `AS node_desc` + 5열 return_cols 명시 |
| `age_service.py:get_ontology_relationships` | `AS desc` → 동일 | `AS rel_desc` + 5열 return_cols 명시 |

### 3.5 데이터 마이그레이션 스크립트 (P5-06)

`scripts/migrate_neo4j_to_kair_graphdb.py` — 통합 마이그레이션 엔트리포인트:

| Phase | 대상 | 설명 |
|-------|------|------|
| Phase A | AGE 온톨로지 그래프 | 기존 `migrate_neo4j_to_age.py` 호출 |
| Phase B | 관계형 테이블 | t2s_tables/columns, analyzer_tables/columns 적재 |

실행 옵션:
- `--graph-only`: AGE 그래프만
- `--tables-only`: 관계형 테이블만
- (기본): 전체 마이그레이션

### 3.6 Docker Compose 통합 구성 (P5-07)

`docker/K-AIR-GraphDB/docker-compose.full.yml` — 4개 서비스 통합:

| 서비스 | 포트 | 의존성 |
|--------|------|--------|
| kair-graphdb | 15432 | - |
| kair-domain-layer | 8002 | kair-graphdb (healthy) |
| kair-text2sql | 8000 | kair-graphdb (healthy) |
| kair-analyzer | 5502 | kair-graphdb (healthy) |

---

## 4. 파일 구조

```
K_Water_v1/
├── docker/
│   └── K-AIR-GraphDB/             ← 네이밍 전환
│       ├── Dockerfile
│       ├── docker-compose.yml      ← 단독 실행
│       ├── docker-compose.full.yml ← 4개 서비스 통합
│       └── init/                   ← DDL 스크립트
│
├── libs/
│   └── age_graph_repository/       ← SDK (Phase 1~4)
│
├── services/                       ← Phase 5 신규
│   ├── K-AIR-domain-layer/
│   │   ├── app/{main,deps,config,routers/ontology}.py
│   │   └── requirements.txt
│   ├── K-AIR-text2sql/
│   │   ├── app/{main,deps,config,routers/text2sql}.py
│   │   └── requirements.txt
│   ├── K-AIR-analyzer/
│   │   ├── app/{main,deps,config,routers/analysis,glossary}.py
│   │   └── requirements.txt
│   └── tests/
│       ├── conftest.py
│       ├── pytest.ini
│       ├── test_e2e_domain_layer.py   (8 tests)
│       ├── test_e2e_text2sql.py       (7 tests)
│       └── test_e2e_analyzer.py      (11 tests)
│
├── scripts/
│   ├── migrate_neo4j_to_age.py
│   └── migrate_neo4j_to_kair_graphdb.py  ← 통합 마이그레이션
│
└── docs/
    ├── Phase1_3_개발_보고서.md
    └── Phase5_개발_보고서.md           ← 본 문서
```

---

## 5. 테스트 결과 요약

| 항목 | 결과 |
|------|------|
| E2E 테스트 총 건수 | **26건** |
| 통과 | **26건 (100%)** |
| 실패 | 0건 |
| 테스트 소요 시간 | 12.18초 |
| 대상 DB | K-AIR-GraphDB (localhost:15432) |

---

## 6. Neo4j → K-AIR-GraphDB 전환 매핑

| K-AIR 서비스 | 기존 (Neo4j) | 전환 후 (K-AIR-GraphDB) |
|---|---|---|
| domain-layer | `Neo4jService` | `AgeConnection` + `AgeService` |
| domain-layer | `SchemaStore.set_neo4j_service()` | `AgeSchemaStore.set_age_service()` |
| text2sql | `Neo4jConnection` / `neo4j_conn` | `PgConnection` / `pg_t2s_conn` |
| text2sql | `neo4j.AsyncGraphDatabase.driver()` | `asyncpg.create_pool()` |
| analyzer | `Neo4jClient` | `PgAnalyzerClient` |
| analyzer | `graph_query_service` | `PgGraphQueryService` |
| analyzer | `glossary_manage_service` | `PgGlossaryService` |
| analyzer | `schema_manage_service` | `PgSchemaManageService` |
| analyzer | `related_tables_service` | `PgRelatedTablesService` |
| analyzer | `data_lineage_service` | `PgLineageService` |
| analyzer | `metadata_enrichment_service` | `PgMetadataService` |
| analyzer | `business_calendar_service` | `PgBusinessCalendarService` |
| analyzer | `phase_ddl` | `PgPhaseDDL` |

---

## 7. 후속 작업 (향후 고려사항)

1. **각 서비스 Dockerfile 작성**: `services/K-AIR-*/Dockerfile` 추가하여 Docker Compose 통합 실행 가능하게
2. **LLM 연동 테스트**: 현재 E2E 테스트는 DB 연동만 검증. 실제 LLM API 호출 포함 테스트 추가 필요
3. **성능 벤치마크**: 대용량 데이터(100K+ rows) 기준 pgvector 검색 성능 측정
4. **프로덕션 환경 설정**: 환경변수 기반 시크릿 관리, SSL 설정, 커넥션 풀 튜닝
5. **CI/CD 파이프라인**: 자동 테스트·빌드·배포 파이프라인 구성
