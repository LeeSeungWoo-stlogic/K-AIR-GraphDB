# PRD: Graph DB 대체 — B안 (PostgreSQL + pgvector + Apache AGE)

> **정책 정합 (2026-04-13)**  
> 프로젝트 기준선: [아키텍처_및_환경_스냅샷_20260413.md](../K_AIR/아키텍처_및_환경_스냅샷_20260413.md). 운영 목표 그래프 스택은 **PostgreSQL + Apache AGE + pgvector**. **우선 적용 문서는 [GraphDB_대체_통합_PRD_v2.md](./GraphDB_대체_통합_PRD_v2.md)** 이며, 본 B안은 **대안 비교·이력 참고**용이다(AGE 도입 단계 서술이 v2와 다를 수 있음).

| 항목 | 내용 |
|------|------|
| **문서 유형** | Product Requirements Document (PRD) |
| **작성일** | 2026-04-06 |
| **기준일(정합)** | 2026-04-13 — 스냅샷과 병기 |
| **배경** | Neo4j 라이선스 이슈(GPLv3/상용)로 인한 Graph DB 대체 필요 |
| **대상 시스템** | K-AIR MSA 서비스 (analyzer, domain-layer, text2sql) + Argus Catalog |
| **선정 전략** | B안 — PostgreSQL(RDB) + pgvector(벡터 검색) + Apache AGE(그래프 확장, 2단계) |
| **관련 문서** | [메타데이터_정비요청_적용가능성분석_v2.md](../K_AIR/메타데이터_정비요청_적용가능성분석_v2.md), [Argus_Catalog_v07_메타매핑_분석.md](../K_AIR/Argus_Catalog_v07_메타매핑_분석.md) |

---

## 1. 배경 및 문제 정의

### 1.1 현재 아키텍처

K-AIR 플랫폼은 3개 MSA 서비스가 Neo4j(Graph DB)를 핵심 저장소로 공유한다.

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  domain-layer │  │   analyzer   │  │   text2sql   │
│   (8002)      │  │              │  │   (8000)     │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────────┬────┴────────────────┘
                    ▼
           ┌──────────────┐
           │   Neo4j       │ ← GPLv3 / Enterprise 상용 라이선스
           │  (bolt:7687)  │
           └──────────────┘
```

### 1.2 문제

| 문제 | 상세 |
|------|------|
| **라이선스** | Neo4j Community는 GPLv3(파생물 소스 공개 의무), Enterprise는 상용 라이선스 필요. K-water 납품 시 라이선스 비용 발생 |
| **대안 부재** | Memgraph(BSL), ArangoDB(BSL), S2Graph(Retired), Kùzu(임베디드) 등 검토 결과, 라이선스 자유 + MSA 호환 + 기능 완성도를 동시 충족하는 Graph DB 오픈소스 없음 |

### 1.3 대안 선택 근거

| 검토 대안 | 라이선스 | MSA 호환 | Cypher | 벡터 검색 | 결론 |
|-----------|---------|---------|--------|----------|------|
| Memgraph | BSL ❌ | ✅ | ✅ | ❌ | 라이선스 문제 동일 |
| ArangoDB | BSL ❌ | ✅ | ❌ (AQL) | ✅ | 라이선스 + 쿼리 전면 재작성 |
| Apache AGE | Apache 2.0 ✅ | ✅ | 서브셋 | ❌ | 기술적 전환 비용 높음(20~30일) |
| Kùzu | MIT ✅ | ❌ (임베디드) | ✅ | ❌ | MSA 아키텍처 불일치 |
| **PostgreSQL + pgvector + AGE** | **모두 자유 ✅** | **✅** | **2단계 가능** | **✅ (pgvector)** | **선정** |

---

## 2. 목표 아키텍처

### 2.1 단계별 전략

#### 1단계: 화성정수장 (노드 수백 개 규모)

```
┌─────────────────────────────────────────────────────┐
│                PostgreSQL 단일 인스턴스                 │
│                                                       │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐ │
│  │ Argus Catalog │  │  온톨로지 관계   │  │  pgvector  │ │
│  │  (기존 스키마)  │  │  (RDB 테이블)   │  │ (벡터 검색) │ │
│  └──────────────┘  └───────────────┘  └────────────┘ │
│                                                       │
│  경로 탐색: WITH RECURSIVE CTE                         │
└─────────────────────────────────────────────────────┘
```

#### 2단계: 전체 K-water 데이터 (노드 수천~수만 개 규모)

```
┌─────────────────────────────────────────────────────┐
│                PostgreSQL 동일 인스턴스                 │
│                                                       │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐ │
│  │ Argus Catalog │  │  Apache AGE    │  │  pgvector  │ │
│  │  (기존 스키마)  │  │ (그래프 확장)   │  │ (벡터 검색) │ │
│  └──────────────┘  └───────────────┘  └────────────┘ │
│                                                       │
│  경로 탐색: AGE Cypher (SQL 래핑)                      │
│  SQL + Cypher + Vector → 동일 트랜잭션 내 혼합 가능      │
└─────────────────────────────────────────────────────┘
```

### 2.2 MSA 서비스 재설계

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  domain-layer    │  │   analyzer       │  │   text2sql       │
│  (온톨로지 CRUD)  │  │ (DDL파싱·메타)   │  │ (자연어→SQL)     │
└──────┬───────────┘  └──────┬───────────┘  └──────┬───────────┘
       │                     │                     │
       └─────────────┬───────┴─────────────────────┘
                     ▼
          ┌─────────────────────┐
          │  OntologyRepository  │  ← Repository 추상화 레이어
          │  (인터페이스)         │
          └──────────┬──────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ RDB 구현  │ │ AGE 구현  │ │ pgvector │
  │(1단계)   │ │(2단계)   │ │ (공통)   │
  └──────────┘ └──────────┘ └──────────┘
                     │
                     ▼
            ┌──────────────┐
            │  PostgreSQL   │ ← Apache 2.0 / PostgreSQL License
            └──────────────┘
```

---

## 3. 데이터베이스 스키마 설계

### 3.1 온톨로지 코어 테이블

```sql
-- 온톨로지 스키마 (기존 Neo4j의 OntologySchema 노드 대체)
CREATE TABLE ontology_schemas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    domain VARCHAR(255),
    version INTEGER DEFAULT 1,
    schema_json JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ
);

-- 온톨로지 노드 (기존 Neo4j의 OntologyType/OntologyNode 대체)
CREATE TABLE ontology_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_id UUID NOT NULL REFERENCES ontology_schemas(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    layer VARCHAR(20) NOT NULL CHECK (layer IN ('KPI','Measure','Driver','Process','Resource')),
    label VARCHAR(100),
    description TEXT,
    data_source VARCHAR(255),
    data_source_schema JSONB,
    materialized_view VARCHAR(255),
    unit VARCHAR(50),
    formula TEXT,
    target_value FLOAT,
    thresholds JSONB,
    time_column VARCHAR(100),
    time_granularity VARCHAR(20),
    aggregation_method VARCHAR(20),
    bpmn_xml TEXT,
    position JSONB,
    properties JSONB,
    instance_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ont_nodes_schema ON ontology_nodes(schema_id);
CREATE INDEX idx_ont_nodes_layer ON ontology_nodes(layer);
CREATE INDEX idx_ont_nodes_name ON ontology_nodes(name);

-- 온톨로지 관계 (기존 Neo4j의 관계 대체)
CREATE TABLE ontology_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES ontology_nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES ontology_nodes(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    description TEXT,
    weight FLOAT,
    lag INTEGER,
    confidence FLOAT,
    source_layer VARCHAR(20),
    target_layer VARCHAR(20),
    from_field VARCHAR(100),
    to_field VARCHAR(100),
    properties JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ont_rel_source ON ontology_relationships(source_id);
CREATE INDEX idx_ont_rel_target ON ontology_relationships(target_id);
CREATE INDEX idx_ont_rel_type ON ontology_relationships(type);

-- 벡터 임베딩 (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE ontology_node_embeddings (
    node_id UUID PRIMARY KEY REFERENCES ontology_nodes(id) ON DELETE CASCADE,
    embedding vector(1536)
);
CREATE INDEX idx_node_emb_hnsw ON ontology_node_embeddings
    USING hnsw (embedding vector_cosine_ops);
```

### 3.2 Analyzer 서비스용 테이블

```sql
-- 테이블 메타 (기존 Neo4j의 Analyzer_Table 노드 대체)
CREATE TABLE analyzer_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    datasource VARCHAR(100),
    schema_name VARCHAR(100),
    name VARCHAR(255) NOT NULL,
    original_name VARCHAR(255),
    description TEXT,
    comment TEXT,
    is_valid BOOLEAN DEFAULT true,
    properties JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(datasource, schema_name, name)
);

-- 컬럼 메타 (기존 Neo4j의 Analyzer_Column 노드 대체)
CREATE TABLE analyzer_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id UUID NOT NULL REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    original_name VARCHAR(255),
    fqn VARCHAR(500) UNIQUE NOT NULL,
    data_type VARCHAR(100),
    nullable BOOLEAN,
    is_primary_key BOOLEAN DEFAULT false,
    is_unique BOOLEAN DEFAULT false,
    default_value TEXT,
    description TEXT,
    comment TEXT,
    is_valid BOOLEAN DEFAULT true,
    properties JSONB
);
CREATE INDEX idx_analyzer_col_table ON analyzer_columns(table_id);

-- FK 관계 (기존 Neo4j의 FK_TO 관계 대체)
CREATE TABLE analyzer_fk_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_column_id UUID NOT NULL REFERENCES analyzer_columns(id) ON DELETE CASCADE,
    to_column_id UUID NOT NULL REFERENCES analyzer_columns(id) ON DELETE CASCADE,
    confidence FLOAT,
    source VARCHAR(20) DEFAULT 'inferred',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_fk_from ON analyzer_fk_relations(from_column_id);
CREATE INDEX idx_fk_to ON analyzer_fk_relations(to_column_id);
```

### 3.3 Text2SQL 서비스용 테이블

```sql
-- 테이블/컬럼 벡터 임베딩 (기존 Neo4j 벡터 인덱스 대체)
CREATE TABLE t2s_table_embeddings (
    table_id UUID PRIMARY KEY REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    text_to_sql_vector vector(1536),
    text_content TEXT
);
CREATE INDEX idx_t2s_table_hnsw ON t2s_table_embeddings
    USING hnsw (text_to_sql_vector vector_cosine_ops);

CREATE TABLE t2s_column_embeddings (
    column_id UUID PRIMARY KEY REFERENCES analyzer_columns(id) ON DELETE CASCADE,
    embedding vector(1536),
    text_content TEXT
);
CREATE INDEX idx_t2s_col_hnsw ON t2s_column_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- 쿼리 캐시 (기존 Neo4j의 T2S_Query 노드 대체)
CREATE TABLE t2s_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    sql_text TEXT,
    embedding vector(1536),
    verified BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_t2s_query_hnsw ON t2s_queries
    USING hnsw (embedding vector_cosine_ops);
```

---

## 4. 개발 범위 및 공수 산정

### 4.1 Phase 1: 핵심 인프라 구축

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P1-01 | DB 스키마 설계 및 마이그레이션 스크립트 | 온톨로지·Analyzer·Text2SQL 테이블 DDL + pgvector 확장 | 2일 |
| P1-02 | OntologyRepository 추상화 레이어 | 인터페이스 정의 + RDB 구현체 (Recursive CTE 기반 경로 탐색) | 3일 |
| P1-03 | AnalyzerRepository 추상화 레이어 | 테이블/컬럼/FK 관계 CRUD + 배치 저장 | 2일 |
| P1-04 | VectorSearchRepository | pgvector 기반 테이블·컬럼·쿼리 벡터 검색 | 2일 |
| | **Phase 1 소계** | | **9일** |

### 4.2 Phase 2: domain-layer 서비스 전환

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P2-01 | neo4j_service.py → PostgreSQL 전환 | `sync_ontology_schema`, `_create_node`, `_create_relationship` 재구현 | 3일 |
| P2-02 | schema_store.py 전환 | CRUD 쿼리 전체(list/get/save/delete) Neo4j→SQLAlchemy 전환 | 3일 |
| P2-03 | ontology_causal.py 전환 | 인과 분석 — 멀티-hop 경로 탐색을 Recursive CTE로 재구현 | 3일 |
| P2-04 | ontology_explorer.py 전환 | 오브젝트 검색, 하위 노드 드릴다운 | 1일 |
| P2-05 | ontology_relationship.py 전환 | ObjectType 간 관계 CRUD | 1일 |
| P2-06 | ontology_data.py 전환 | 데이터 조회, 비즈니스 캘린더 | 1일 |
| P2-07 | schema_store_behavior.py / scenario.py | What-if 시뮬레이션 관련 저장소 전환 | 2일 |
| P2-08 | neo4j_labels.py 제거 및 의존성 정리 | Labels 상수 참조 제거, import 정리 | 0.5일 |
| | **Phase 2 소계** | | **14.5일** |

### 4.3 Phase 3: text2sql 서비스 전환

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P3-01 | neo4j.py (build_sql_context_parts) 전환 | 벡터 검색 + FK 관계 조회 — 가장 큰 파일(900+줄) | 5일 |
| P3-02 | graph_search.py 전환 | 테이블/컬럼 벡터 검색 Neo4j→pgvector | 2일 |
| P3-03 | neo4j_utils.py 전환 | FK 관계 조회, 다중-hop 관련 테이블 탐색 | 2일 |
| P3-04 | neo4j_bootstrap.py 전환 | 시작 시 제약조건/인덱스 생성 → Alembic 마이그레이션으로 대체 | 1일 |
| P3-05 | deps.py Neo4j 연결 제거 | Neo4jConnection → asyncpg 풀 통합 | 0.5일 |
| P3-06 | 쿼리 캐시/히스토리 전환 | T2S_Query, ValueMapping 등 Neo4j 노드 → PostgreSQL 테이블 | 1.5일 |
| | **Phase 3 소계** | | **12일** |

### 4.4 Phase 4: analyzer 서비스 전환

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P4-01 | neo4j_client.py → asyncpg 전환 | 배치 쿼리, 그래프 결과 반환 → SQL 배치 INSERT | 2일 |
| P4-02 | phase_ddl.py 전환 | DDL 파싱 결과 저장 Neo4j→PostgreSQL | 1.5일 |
| P4-03 | phase_post.py / phase_llm.py 전환 | LLM 분석 결과 저장 | 1.5일 |
| P4-04 | phase_metadata.py 전환 | 메타데이터 보강 결과 저장 | 1일 |
| P4-05 | phase_lineage.py 전환 | 리니지 관계 저장 | 1일 |
| P4-06 | graph_query_service / related_tables_service | 관련 테이블 조회 서비스 전환 | 1.5일 |
| P4-07 | 기타 서비스 전환 | glossary, schema_manage, business_calendar 등 | 1.5일 |
| | **Phase 4 소계** | | **10일** |

### 4.5 Phase 5: 통합 테스트 및 안정화

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P5-01 | 단위 테스트 작성 | Repository 레이어 테스트 + 기존 테스트 마이그레이션 | 3일 |
| P5-02 | 통합 테스트 | 3개 서비스 간 연동 테스트 (벡터 검색→FK 조회→인과 분석) | 2일 |
| P5-03 | 성능 벤치마크 | Neo4j 기존 성능 대비 비교 (경로 탐색, 벡터 검색) | 1일 |
| P5-04 | 데이터 마이그레이션 스크립트 | 화성정수장 Neo4j dump → PostgreSQL 이전 | 2일 |
| P5-05 | Docker/배포 설정 | docker-compose에서 Neo4j 제거, PostgreSQL 설정 통합 | 1일 |
| | **Phase 5 소계** | | **9일** |

### 4.6 Phase 6 (2단계, 조건부): Apache AGE 확장

| 작업 ID | 작업 내용 | 상세 | 공수 |
|---------|----------|------|------|
| P6-01 | AGE 확장 설치 및 그래프 생성 | `CREATE EXTENSION age` + 온톨로지 그래프 정의 | 0.5일 |
| P6-02 | AgeOntologyRepository 구현 | Recursive CTE → Cypher(SQL 래핑) 전환 | 3일 |
| P6-03 | 데이터 마이그레이션 | RDB 온톨로지 테이블 → AGE 그래프 이전 | 1일 |
| P6-04 | 성능 검증 | 대규모 데이터에서 Recursive CTE vs AGE Cypher 비교 | 1일 |
| | **Phase 6 소계** | | **5.5일** |

---

## 5. 공수 총괄

### 5.1 1단계 (화성정수장, 필수)

| Phase | 내용 | 공수 |
|-------|------|------|
| Phase 1 | 핵심 인프라 (스키마 + Repository 추상화) | 9일 |
| Phase 2 | domain-layer 전환 | 14.5일 |
| Phase 3 | text2sql 전환 | 12일 |
| Phase 4 | analyzer 전환 | 10일 |
| Phase 5 | 통합 테스트 및 안정화 | 9일 |
| **1단계 합계** | | **54.5일** |

> **인력 2명 병렬 진행 시**: Phase 2+3을 병렬(14.5일), Phase 4를 뒤이어(10일), Phase 5 공통(9일) → **약 34~38일 (7~8주)**

### 5.2 2단계 (전체 K-water, 조건부)

| Phase | 내용 | 공수 |
|-------|------|------|
| Phase 6 | Apache AGE 확장 | 5.5일 |
| **2단계 합계** | | **5.5일** |

> 노드 수가 수천 개를 초과하고 Recursive CTE 성능이 요구사항(200ms)을 미충족하는 시점에 실행

### 5.3 전체 공수 요약

| 구분 | 공수 (1인) | 공수 (2인 병렬) | 비고 |
|------|-----------|---------------|------|
| **1단계 필수** | 54.5일 | ~34~38일 | 화성정수장 |
| **2단계 조건부** | 5.5일 | 5.5일 | 확장 시에만 |
| **합계** | **60일** | **~40~44일** | |

---

## 6. 리스크 및 완화 방안

| 리스크 | 영향도 | 완화 방안 |
|--------|--------|----------|
| Recursive CTE 성능 한계 (대규모 멀티-hop) | 중 | 2단계 Apache AGE 확장으로 대응. 1단계에서 Repository 추상화 선 적용 |
| Apache AGE Cypher 서브셋 제한 | 중 | AGE 미지원 문법은 SQL 폴백으로 처리. OPTIONAL MATCH 등은 LEFT JOIN으로 대체 |
| pgvector 성능 (대규모 벡터) | 낮 | pgvector HNSW 인덱스는 100만 벡터 이상에서도 sub-10ms. 현 규모 문제 없음 |
| 기존 Neo4j 데이터 마이그레이션 | 중 | Phase 5에서 전용 마이그레이션 스크립트 개발. JSON 중간 포맷으로 변환 |
| Argus Catalog과의 스키마 충돌 | 낮 | 온톨로지 테이블은 `ontology_` 접두사, Analyzer는 `analyzer_` 접두사로 네임스페이스 분리 |

---

## 7. 기술 요구사항

### 7.1 인프라

| 항목 | 요구사항 |
|------|---------|
| PostgreSQL 버전 | 15 이상 (pgvector 0.7+ 호환) |
| pgvector 확장 | 0.7 이상 (HNSW 인덱스 지원) |
| Apache AGE (2단계) | 1.5 이상 (PostgreSQL 15/16 호환) |
| Python 버전 | 3.11 이상 |
| 비동기 DB 드라이버 | asyncpg 0.29+ |
| ORM | SQLAlchemy 2.0+ (async) |

### 7.2 주요 의존성 변경

| 서비스 | 제거 | 추가 |
|--------|------|------|
| domain-layer | `neo4j` (Python 드라이버) | `asyncpg`, `sqlalchemy[asyncio]`, `pgvector` |
| text2sql | `neo4j` | `pgvector` (asyncpg는 기존 사용 중) |
| analyzer | `neo4j` | `asyncpg`, `sqlalchemy[asyncio]` |

---

## 8. 성공 기준

| 기준 | 측정 방법 | 목표 |
|------|----------|------|
| 기능 동등성 | 기존 Neo4j 기반 API 엔드포인트가 동일하게 동작 | 100% API 호환 |
| 벡터 검색 성능 | 테이블/컬럼 유사도 검색 응답 시간 | ≤ 50ms (현재 Neo4j 대비 동등 이상) |
| 경로 탐색 성능 (1단계) | 온톨로지 5-hop 인과 분석 응답 시간 (노드 500개) | ≤ 200ms |
| 경로 탐색 성능 (2단계) | 온톨로지 5-hop 인과 분석 응답 시간 (노드 10,000개) | ≤ 500ms (AGE 적용) |
| 라이선스 | 사용된 모든 DB 구성요소의 라이선스 | Apache 2.0 / PostgreSQL / MIT |
| 인프라 단순화 | 운영 DB 서버 수 | Neo4j 서버 제거 → PostgreSQL 단일 |

---

## 9. 일정 로드맵

```
Week 1-2:  [Phase 1] 핵심 인프라 — 스키마 + Repository 추상화
Week 3-5:  [Phase 2] domain-layer 전환    ← 개발자 A
           [Phase 3] text2sql 전환         ← 개발자 B (병렬)
Week 5-7:  [Phase 4] analyzer 전환        ← A+B 합류
Week 7-8:  [Phase 5] 통합 테스트 + 마이그레이션 + 안정화
───────────────────────────────────────────────────
Week 8 완료: 1단계 배포 (화성정수장)

... (데이터 확장 시) ...

Week N:    [Phase 6] Apache AGE 확장 (5.5일)
```

---

## 10. 부록: Argus 기존 서비스 활용 가능성

Argus 레포지토리 내 기존 서비스 중 B안에 활용 가능한 기술은 별도 검토 결과 참조.

| Argus 서비스 | 활용 가능 영역 | 상세 |
|-------------|--------------|------|
| argus-catalog-server | 메타데이터 저장, 표준 사전, 품질, 리니지 | 이미 PostgreSQL + asyncpg + pgvector 스택 |
| argus-rag-server | 벡터 검색 인프라 | pgvector + 임베딩 파이프라인 재활용 가능 |
| argus-data-engineer-ai-agent | text2sql 대체 가능성 | Catalog API 기반 ReAct 에이전트 |
| argus-catalog-ui | 온톨로지 시각화 기반 | @xyflow/react 그래프 UI 컴포넌트 |
