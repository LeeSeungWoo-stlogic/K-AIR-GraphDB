# PRD v2: K-AIR Neo4j 대체 — PostgreSQL + Apache AGE + pgvector + Argus Catalog 통합

| 항목 | 내용 |
|------|------|
| **문서 유형** | Product Requirements Document (PRD) v2 |
| **작성일** | 2026-04-06 |
| **프로젝트 기준선** | [아키텍처_및_환경_스냅샷_20260413.md](../K_AIR/아키텍처_및_환경_스냅샷_20260413.md) (Neo4j MVP → AGE+pgvector 운영) |
| **이전 버전** | [GraphDB_대체_B안_PRD.md](GraphDB_대체_B안_PRD.md) — 본 문서로 정책 통합, B안은 참고 |
| **변경 사유** | 1) AGE를 "조건부 2단계"가 아닌 **1단계부터 도입** (온톨로지 그래프 관계는 Graph DB 없이 의미 있게 활용 불가) 2) Argus 기존 서비스와의 역할 분담을 정확히 구분 |
| **대상 시스템** | K-AIR MSA (analyzer, domain-layer, text2sql) + Argus 플랫폼 |

---

## 1. 핵심 전제

### 1.1 v1 PRD의 오류 정정

v1 PRD에서는 Apache AGE를 "노드 수 확장 시에만 도입하는 2단계 옵션"으로 분류했다. 이는 다음 사실을 간과한 판단이었다:

> **온톨로지 5계층 관계의 핵심 가치는 "경로 탐색"이다.**
> 단순 저장이 아니라 `Resource → Process → Measure → KPI` 관계 체인을 순회하여 인과 관계를 추출하는 것이 온톨로지의 존재 이유이며, 이것은 본질적으로 그래프 연산이다.

따라서 본 PRD v2에서는:
- **Apache AGE를 1단계부터 도입**하여 온톨로지 그래프 기능을 확보
- Argus Catalog이 **이미 보유한 범용 카탈로그 기능은 그대로 활용**하되, 이를 "K-AIR 핵심 기능 대체"로 과대 평가하지 않음

### 1.2 역할 분담의 명확화

| 영역 | 담당 | 근거 |
|------|------|------|
| **온톨로지 5계층 관계 정의·탐색** | **Apache AGE (신규)** | 그래프 경로 탐색 필수 — Argus에 없음 |
| **인과 분석 (멀티-hop)** | **Apache AGE (신규)** | `[*1..5]` 가변 경로 순회 — RDB CTE 불충분 |
| **What-if 시뮬레이션 전파** | **Apache AGE + 서비스 로직 (신규)** | 그래프 전파 모델 — Argus에 없음 |
| 메타데이터 CRUD (테이블/컬럼) | Argus Catalog (기존) | `catalog_datasets`, `catalog_dataset_schemas` |
| 벡터 검색 (시맨틱) | Argus Catalog + RAG Server (기존) | pgvector 하이브리드 검색 이미 구현 |
| 표준 사전·동의어·코드 | Argus Catalog (기존) | `standard_word`, `synonym_group_id`, `code_group` |
| 리니지·FK 관계 | Argus Catalog (기존) | `dataset_lineage`, `column_mapping` |
| 품질 규칙·프로파일 | Argus Catalog (기존) | `quality_rule`, `quality_result`, `data_profile` |

**요약**: Argus는 **범용 데이터 카탈로그**, AGE는 **온톨로지 그래프 엔진**. 둘은 같은 PostgreSQL 인스턴스 위에서 상호 보완한다.

---

## 2. 문제 정의

### 2.1 현재 아키텍처의 문제

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  domain-layer │  │   analyzer   │  │   text2sql   │
│   (8002)      │  │              │  │   (8000)     │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────────┬────┴────────────────┘
                    ▼
           ┌──────────────┐       ┌────────────────────┐
           │   Neo4j       │       │  Argus Catalog      │
           │ (bolt:7687)   │       │  (PostgreSQL:5432)  │
           │ GPLv3/상용 ❌  │       │  Apache 2.0 ✅      │
           └──────────────┘       └────────────────────┘
           별도 서버 운영 필요         이미 운영 중
```

| 문제 | 상세 |
|------|------|
| **Neo4j 라이선스** | Community(GPLv3) — 파생물 소스 공개 의무, Enterprise — 상용 라이선스 비용 |
| **이중 인프라 운영** | Neo4j 서버 + PostgreSQL 서버를 별도 관리 |
| **대안 Graph DB 부재** | Memgraph(BSL), ArangoDB(BSL), S2Graph(Retired), Kùzu(임베디드) — 라이선스 자유+MSA 호환 동시 충족 불가 |

### 2.2 Graph DB 대안 검토 결과 요약

| 대안 | 라이선스 | MSA | Cypher | 벡터 | 판정 |
|------|---------|-----|--------|------|------|
| Memgraph | BSL ❌ | ✅ | ✅ | ❌ | 라이선스 동일 문제 |
| ArangoDB | BSL ❌ | ✅ | ❌ (AQL) | ✅ | 라이선스 + 쿼리 전면 재작성 |
| Kùzu | MIT ✅ | ❌ 임베디드 | ✅ | ❌ | MSA 불일치 |
| S2Graph | Apache 2.0 | - | ❌ | ❌ | **2020년 Retired** |
| **Apache AGE** | **Apache 2.0 ✅** | **✅** | **서브셋** | ❌ | **선정 (pgvector 병용)** |

---

## 3. 목표 아키텍처

### 3.1 통합 아키텍처

```
┌───────────────────────────────────────────────────────────────────────┐
│                       PostgreSQL 단일 인스턴스                          │
│                                                                       │
│  ┌─────────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │   Argus Catalog      │  │   Apache AGE      │  │    pgvector     │  │
│  │   (기존 스키마)        │  │ (그래프 확장)      │  │  (벡터 검색)     │  │
│  │                      │  │                   │  │                 │  │
│  │ · catalog_datasets   │  │ · ontology_graph  │  │ · 테이블 임베딩  │  │
│  │ · standard_word      │  │   ├─ :KPI         │  │ · 컬럼 임베딩   │  │
│  │ · code_group/value   │  │   ├─ :Measure     │  │ · 쿼리 임베딩   │  │
│  │ · quality_rule       │  │   ├─ :Driver      │  │                 │  │
│  │ · dataset_lineage    │  │   ├─ :Process     │  │ HNSW 인덱스     │  │
│  │ · glossary_terms     │  │   └─ :Resource    │  │ 코사인 유사도    │  │
│  │                      │  │                   │  │                 │  │
│  │   SQL로 접근          │  │   Cypher로 접근    │  │  SQL로 접근      │  │
│  └─────────────────────┘  └──────────────────┘  └─────────────────┘  │
│                                                                       │
│           동일 트랜잭션 내에서 SQL + Cypher + Vector 혼합 가능            │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.2 MSA 서비스 구성

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  domain-layer    │  │   analyzer       │  │   text2sql       │
│  (온톨로지 CRUD   │  │ (DDL파싱·메타     │  │ (자연어→SQL)     │
│   + 인과 분석     │  │  보강·리니지)     │  │                  │
│   + What-if)     │  │                  │  │                  │
└──────┬───────────┘  └──────┬───────────┘  └──────┬───────────┘
       │                     │                     │
       │ AGE Cypher          │ SQL (asyncpg)       │ pgvector + SQL
       │ (온톨로지 그래프)     │ (메타 저장)          │ (벡터 검색)
       │                     │                     │
       └─────────────┬───────┴─────────────────────┘
                     ▼
            ┌──────────────────┐
            │   PostgreSQL      │
            │  + Apache AGE     │   ← 모두 Apache 2.0 / PostgreSQL License
            │  + pgvector       │
            └──────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│ Argus Catalog    │   │ Argus RAG Server │
│ (범용 카탈로그)   │   │ (임베딩 파이프라인) │
│ REST API 4600    │   │ REST API 4800    │
└──────────────────┘   └──────────────────┘
```

### 3.3 핵심 데이터 흐름

```
1) 메타데이터 수집
   DDL/원천 → analyzer → Argus Catalog (SQL INSERT)

2) 온톨로지 생성
   PDF/텍스트 → domain-layer → Apache AGE (Cypher CREATE)

3) 벡터 임베딩
   테이블·컬럼 → Argus RAG Server → pgvector (SQL INSERT)

4) Text2SQL
   자연어 → pgvector 벡터 검색 → Argus Catalog FK/메타 조회
         → LLM SQL 생성 → 타겟 DB 실행

5) 인과 분석
   KPI 노드 지정 → AGE Cypher 멀티-hop 경로 탐색
                → Argus Catalog 코드값·표준 용어 보강
                → 통계 분석 + LLM 보고서

6) 연계 쿼리 (AGE + Argus 동일 트랜잭션)
   AGE에서 온톨로지 경로 탐색 결과 → SQL로 Argus Catalog 표준 용어 매칭
```

---

## 4. Apache AGE 온톨로지 그래프 설계

### 4.1 그래프 초기화

```sql
-- 확장 설치
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector

-- 그래프 생성
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('ontology_graph');
```

### 4.2 노드 레이블 (5계층)

```sql
-- KPI 노드 생성 예시
SELECT * FROM cypher('ontology_graph', $$
    CREATE (k:KPI {
        id: 'kpi_001',
        schema_id: 'schema_001',
        name: '일평균탁도',
        unit: 'NTU',
        formula: 'AVG(시간별 탁도, 24건)',
        target_value: 0.5,
        data_source: 'WTP_QUALITY'
    })
    RETURN k
$$) AS (node agtype);

-- Measure 노드
SELECT * FROM cypher('ontology_graph', $$
    CREATE (m:Measure {
        id: 'measure_001',
        schema_id: 'schema_001',
        name: '탁도_시간데이터',
        unit: 'NTU',
        time_granularity: 'hour',
        aggregation_method: 'mean',
        value_type: 'MO'
    })
    RETURN m
$$) AS (node agtype);

-- Process 노드
SELECT * FROM cypher('ontology_graph', $$
    CREATE (p:Process {
        id: 'process_001',
        schema_id: 'schema_001',
        name: '24건평균산출',
        description: '시간별 탁도 24건을 일평균으로 산출'
    })
    RETURN p
$$) AS (node agtype);

-- Resource 노드
SELECT * FROM cypher('ontology_graph', $$
    CREATE (r:Resource {
        id: 'resource_001',
        schema_id: 'schema_001',
        name: '화성정수장',
        facility_type: 'WTP'
    })
    RETURN r
$$) AS (node agtype);
```

### 4.3 관계 타입

```sql
-- Process → Measure (PRODUCES)
SELECT * FROM cypher('ontology_graph', $$
    MATCH (p:Process {id: 'process_001'})
    MATCH (m:Measure {id: 'measure_001'})
    CREATE (p)-[:PRODUCES {weight: 1.0}]->(m)
$$) AS (result agtype);

-- Measure → KPI (MEASURED_AS)
SELECT * FROM cypher('ontology_graph', $$
    MATCH (m:Measure {id: 'measure_001'})
    MATCH (k:KPI {id: 'kpi_001'})
    CREATE (m)-[:MEASURED_AS {confidence: 0.95}]->(k)
$$) AS (result agtype);

-- Resource → Process (OPERATES)
SELECT * FROM cypher('ontology_graph', $$
    MATCH (r:Resource {id: 'resource_001'})
    MATCH (p:Process {id: 'process_001'})
    CREATE (r)-[:OPERATES]->(p)
$$) AS (result agtype);
```

### 4.4 핵심 쿼리: 인과 체인 탐색

```sql
-- KPI의 원인 체인을 최대 5단계까지 역추적
SELECT * FROM cypher('ontology_graph', $$
    MATCH path = (source)-[*1..5]->(target:KPI {id: 'kpi_001'})
    RETURN
        [n IN nodes(path) | {id: n.id, name: n.name, label: label(n)}] AS chain,
        [r IN relationships(path) | type(r)] AS relation_types,
        length(path) AS depth
    ORDER BY depth
$$) AS (chain agtype, relation_types agtype, depth agtype);
```

### 4.5 연계 쿼리: AGE + Argus Catalog (동일 트랜잭션)

```sql
-- 1) AGE에서 온톨로지 경로 탐색
WITH ontology_measures AS (
    SELECT * FROM cypher('ontology_graph', $$
        MATCH (m:Measure)-[:MEASURED_AS]->(k:KPI {name: '일평균탁도'})
        RETURN m.name AS measure_name, m.data_source AS data_source, m.value_type AS value_type
    $$) AS (measure_name agtype, data_source agtype, value_type agtype)
)
-- 2) Argus Catalog에서 표준 용어 + 코드값 매칭
SELECT
    om.measure_name::text,
    om.data_source::text,
    st.term_name AS standard_term,
    cv.code_name AS value_type_name,
    ds.description AS dataset_description
FROM ontology_measures om
LEFT JOIN catalog_standard_term st
    ON st.physical_name = om.data_source::text
LEFT JOIN catalog_code_value cv
    ON cv.code_value = om.value_type::text
    AND cv.group_id = (SELECT id FROM catalog_code_group WHERE group_name = '값형태코드')
LEFT JOIN catalog_datasets ds
    ON ds.name = om.data_source::text;
```

---

## 5. Argus Catalog 활용 범위 (기존 기능 — 신규 개발 불필요)

### 5.1 메타데이터 CRUD

| 기능 | Argus 테이블 | API |
|------|-------------|-----|
| 테이블 메타 등록·조회 | `catalog_datasets` | `GET/POST /api/v1/catalog/datasets` |
| 컬럼 스키마 관리 | `catalog_dataset_schemas` | `GET /api/v1/catalog/datasets/{id}/schema` |
| 확장 속성 (KV) | `catalog_dataset_properties` | key-value 자유 확장 |
| 스키마 변경 이력 | `catalog_schema_snapshots` | 자동 추적 |

### 5.2 표준 사전 (v0.7 요구사항 대응)

| 기능 | Argus 테이블 | 비고 |
|------|-------------|------|
| 표준 단어 | `catalog_standard_word` | `synonym_group_id`로 동의어 관리 |
| 표준 용어 | `catalog_standard_term` | 물리명↔논리명 매핑 |
| 용어↔컬럼 매핑 | `catalog_term_column_mapping` | MATCHED/SIMILAR/VIOLATION |
| 코드 그룹·값 | `catalog_code_group`, `catalog_code_value` | MO/AV/AC 등 값형태 코드 등록 |
| 표준 도메인 | `catalog_standard_domain` | 데이터타입 표준 |

### 5.3 벡터 검색

| 기능 | Argus 서비스 | 비고 |
|------|-------------|------|
| 시맨틱 검색 | Catalog Server `search/service.py` | pgvector 코사인 유사도 |
| 하이브리드 검색 | 동일 | 키워드 + 시맨틱 가중치 합산 |
| 임베딩 파이프라인 | RAG Server `embedding/` | SentenceTransformer / OpenAI / Ollama |
| 멀티 Collection | RAG Server `collection/` | 테이블·컬럼·쿼리별 독립 관리 |

### 5.4 리니지·품질

| 기능 | Argus 테이블 | 비고 |
|------|-------------|------|
| 데이터셋 리니지 | `argus_dataset_lineage` | source↔target, relation_type |
| 컬럼 레벨 리니지 | `argus_dataset_column_mapping` | transform_type 포함 |
| 품질 규칙 | `catalog_quality_rule` | 7종 체크 + CUSTOM_SQL |
| 품질 결과·점수 | `catalog_quality_result`, `quality_score` | 이력 관리 |
| 데이터 프로파일 | `catalog_data_profile` | 컬럼 통계 |

---

## 6. 신규 개발 범위 (온톨로지 핵심 — 그래프 필수)

### 6.1 Phase 1: Apache AGE 인프라 + 온톨로지 코어 (10일)

| ID | 작업 | 상세 | 공수 |
|----|------|------|------|
| P1-01 | AGE 확장 설치 + 그래프 초기화 | `CREATE EXTENSION age`, `create_graph('ontology_graph')`, 레이블 정의 | 1일 |
| P1-02 | 온톨로지 스키마 관리 테이블 | `ontology_schemas` RDB 테이블 (JSON 블롭 + 메타) — AGE 그래프와 병행 | 1일 |
| P1-03 | OntologyGraphRepository | AGE Cypher 기반 노드·관계 CRUD + 경로 탐색 인터페이스 | 3일 |
| P1-04 | Argus Catalog 연동 어댑터 | AGE 노드 ↔ Catalog dataset/code 크로스 조회 쿼리 세트 | 2일 |
| P1-05 | pgvector 임베딩 테이블 | 테이블·컬럼·쿼리 벡터 임베딩 DDL + HNSW 인덱스 | 1일 |
| P1-06 | 벡터 검색 Repository | Argus RAG Server 패턴 참조, pgvector 기반 검색 모듈 | 2일 |

### 6.2 Phase 2: domain-layer 서비스 전환 (16일)

| ID | 작업 | 상세 | 공수 |
|----|------|------|------|
| P2-01 | neo4j_service.py → AGE 전환 | `sync_ontology_schema` — AGE Cypher로 노드·관계 동기화 | 3일 |
| P2-02 | schema_store.py 전환 | 스키마 CRUD — RDB 메타 + AGE 그래프 이중 저장 | 3일 |
| P2-03 | **ontology_causal.py 전환** | **인과 분석 — AGE `[*1..5]` 가변 경로 탐색 + Argus 코드값 보강** | 4일 |
| P2-04 | ontology_explorer.py 전환 | 오브젝트 검색·드릴다운 — AGE 기반 | 1일 |
| P2-05 | ontology_relationship.py 전환 | ObjectType 관계 CRUD — AGE 관계 생성/수정/삭제 | 1일 |
| P2-06 | ontology_data.py 전환 | 데이터 조회·비즈니스 캘린더 — SQL 쿼리 | 1일 |
| P2-07 | schema_store_behavior.py / scenario.py | **What-if 시뮬레이션 — AGE 전파 경로 + 통계 모델** | 2.5일|
| P2-08 | neo4j_labels.py 제거·의존성 정리 | Labels 상수 제거, `neo4j` 패키지 제거 | 0.5일 |

### 6.3 Phase 3: text2sql 서비스 전환 (10일)

| ID | 작업 | 상세 | 공수 |
|----|------|------|------|
| P3-01 | neo4j.py → pgvector + SQL 전환 | 벡터 검색(`db.index.vector.queryNodes`) → pgvector, FK 조회 → Argus lineage API/SQL | 4일 |
| P3-02 | graph_search.py 전환 | 테이블·컬럼 벡터 검색 → pgvector HNSW | 1.5일 |
| P3-03 | neo4j_utils.py 전환 | FK·관련 테이블 탐색 → Argus `dataset_lineage` JOIN 또는 단순 CTE | 1.5일 |
| P3-04 | deps.py / bootstrap 전환 | Neo4jConnection 제거 → asyncpg 풀 통합 | 1일 |
| P3-05 | 쿼리 캐시·히스토리 전환 | T2S_Query 등 Neo4j 노드 → PostgreSQL 테이블 + pgvector 인덱스 | 2일 |

### 6.4 Phase 4: analyzer 서비스 전환 (8일)

| ID | 작업 | 상세 | 공수 |
|----|------|------|------|
| P4-01 | neo4j_client.py → asyncpg 전환 | 배치 쿼리 → Argus Catalog SQL INSERT (메타는 Catalog 테이블에 직접 저장) | 2일 |
| P4-02 | phase_ddl.py 전환 | DDL 파싱 결과 → `catalog_datasets` + `catalog_dataset_schemas` 저장 | 1.5일 |
| P4-03 | phase_post.py / phase_llm.py 전환 | LLM 분석 결과 → `catalog_datasets.description` 업데이트 | 1일 |
| P4-04 | phase_metadata.py 전환 | 메타데이터 보강 → Catalog API 호출 | 1일|
| P4-05 | phase_lineage.py 전환 | 리니지 → `argus_dataset_lineage` + `column_mapping` | 1일|
| P4-06 | 관련 서비스 전환 | graph_query, related_tables, glossary, schema_manage 등 | 1.5일 |

### 6.5 Phase 5: 통합 테스트·안정화·마이그레이션 (9일)

| ID | 작업 | 상세 | 공수 |
|----|------|------|------|
| P5-01 | 단위 테스트 | AGE Repository + pgvector 검색 + Argus 연동 | 3일 |
| P5-02 | 통합 테스트 | 3개 서비스 E2E (벡터→FK→인과분석→보고서) | 2일 |
| P5-03 | 성능 벤치마크 | Neo4j vs AGE 경로 탐색, pgvector vs Neo4j 벡터 검색 | 1일 |
| P5-04 | 데이터 마이그레이션 | 화성정수장 Neo4j dump → AGE 그래프 + Argus Catalog 이전 | 2일 |
| P5-05 | Docker/배포 설정 | Neo4j 컨테이너 제거, PostgreSQL에 AGE+pgvector 통합 | 1일 |

---

## 7. 공수 총괄

| Phase | 내용 | 공수 |
|-------|------|------|
| Phase 1 | AGE 인프라 + 온톨로지 코어 + 벡터 검색 | 10일 |
| Phase 2 | domain-layer 전환 (인과 분석·What-if 포함) | 16일 |
| Phase 3 | text2sql 전환 | 10일 |
| Phase 4 | analyzer 전환 | 8일 |
| Phase 5 | 통합 테스트·안정화·마이그레이션 | 9일 |
| **합계** | | **53일** |

### 병렬 진행 시

| 구간 | 개발자 A | 개발자 B | 기간 |
|------|---------|---------|------|
| Week 1~2 | Phase 1 (인프라) | Phase 1 (인프라) | 공동 10일 → 5~6일 |
| Week 3~5 | **Phase 2** (domain-layer) | **Phase 3** (text2sql) | 병렬 16일 / 10일 |
| Week 5~7 | Phase 4 (analyzer) | Phase 4 (analyzer) | 공동 8일 → 4~5일 |
| Week 7~8 | Phase 5 (테스트·마이그레이션) | Phase 5 | 공동 9일 → 5~6일 |
| **합계** | | | **약 30~33일 (6~7주)** |

### v1 PRD 대비 변경

| 항목 | v1 PRD | v2 PRD (본 문서) | 차이 |
|------|--------|----------------|------|
| AGE 도입 시점 | 2단계 (조건부) | **1단계 (필수)** | 즉시 도입 |
| Recursive CTE | Phase 1~5에서 사용 | 불필요 (AGE 직접 사용) | 삭제 |
| Argus 역할 | "대부분 대체 가능" | **범용 카탈로그에 한정** | 과대 평가 정정 |
| 온톨로지 핵심 | 신규 개발 필요 (비중 낮게 기술) | **프로젝트 핵심으로 명시** | 위상 정정 |
| 1인 공수 | 54.5일 + 5.5일(조건부) | **53일** | 1.5일 감소 (CTE→AGE 전환) |
| 2인 공수 | 34~38일 + 5.5일 | **30~33일** | 4~10일 단축 |

---

## 8. 기술 요구사항

### 8.1 인프라

| 항목 | 요구사항 |
|------|---------|
| PostgreSQL | 15 이상 |
| Apache AGE | 1.5 이상 (PG15/16 호환) |
| pgvector | 0.7 이상 (HNSW 인덱스) |
| Python | 3.11 이상 |
| asyncpg | 0.29+ |
| SQLAlchemy | 2.0+ (async) |

### 8.2 라이선스

| 구성요소 | 라이선스 | 상업적 자유 |
|---------|---------|-----------|
| PostgreSQL | PostgreSQL License | ✅ 완전 자유 |
| Apache AGE | Apache 2.0 | ✅ 완전 자유 |
| pgvector | PostgreSQL License | ✅ 완전 자유 |
| Argus Catalog | 자체 (사내) | ✅ |

### 8.3 의존성 변경

| 서비스 | 제거 | 추가/유지 |
|--------|------|----------|
| domain-layer | `neo4j` 드라이버 | `asyncpg`, `sqlalchemy[asyncio]` |
| text2sql | `neo4j` 드라이버 | `pgvector` (asyncpg 기존 유지) |
| analyzer | `neo4j` 드라이버 | `asyncpg`, `sqlalchemy[asyncio]` |

---

## 9. Apache AGE 기술 제약 및 대응

| AGE 제약 | 영향 | 대응 방안 |
|---------|------|----------|
| 멀티레이블 미지원 | 노드당 1개 레이블만 가능 | 5계층을 각각 독립 레이블로 사용 (KPI, Measure 등). `properties`에 추가 분류 저장 |
| CALL 프로시저 미지원 | 벡터 검색 통합 쿼리 불가 | 벡터 검색은 pgvector SQL로 분리 → 결과를 AGE Cypher의 WHERE 절에 전달 |
| OPTIONAL MATCH 제한 | 일부 쿼리 패턴 불가 | SQL LEFT JOIN으로 대체 |
| MERGE ON CREATE/MATCH SET 제한 | 조건부 upsert 제한 | PL/pgSQL 함수로 존재 확인 후 CREATE/SET 분리 |
| SQL 래핑 필수 | 모든 Cypher를 `cypher()` 함수로 감싸야 함 | Repository 레이어에서 캡슐화, 서비스 코드에서는 추상 인터페이스만 사용 |

---

## 10. 리스크 및 완화

| 리스크 | 영향도 | 완화 방안 |
|--------|--------|----------|
| AGE Cypher 서브셋 제한 | 중 | 미지원 문법은 SQL 폴백. Repository 캡슐화로 서비스 코드 영향 차단 |
| AGE 안정성 (비교적 젊은 프로젝트) | 중 | 한국 기업(비트나인) 주도 개발로 국내 지원 가능. PostgreSQL 위 확장이므로 ACID 보장 |
| 대규모 그래프 성능 | 중 | AGE 노드 테이블에 PG 인덱스 추가 가능. 10만 노드 이상 시 파티셔닝 검토 |
| Neo4j 데이터 마이그레이션 | 중 | JSON 중간 포맷으로 export → AGE Cypher bulk CREATE. Phase 5에서 전용 스크립트 |
| Argus Catalog 스키마 충돌 | 낮 | AGE 그래프는 `ontology_graph` 스키마에 격리, Argus는 `public` 스키마 |

---

## 11. 성공 기준

| 기준 | 목표 |
|------|------|
| 기능 동등성 | 기존 Neo4j 기반 API 100% 호환 |
| 인과 분석 성능 (노드 500개, 5-hop) | ≤ 200ms |
| 벡터 검색 성능 | ≤ 50ms |
| 라이선스 | 전 구성요소 Apache 2.0 / PostgreSQL License |
| 인프라 | Neo4j 서버 제거 → PostgreSQL 단일 인스턴스 |
| Argus 통합 | 동일 트랜잭션 내 AGE + Catalog SQL 혼합 쿼리 동작 |

---

## 12. 일정 로드맵

```
Week 1~2:   [Phase 1] AGE + pgvector 인프라 구축
              · AGE 설치·그래프 초기화
              · 온톨로지 Repository 구현
              · Argus Catalog 연동 어댑터
              · 벡터 검색 모듈

Week 3~5:   [Phase 2] domain-layer 전환       ← 개발자 A
            [Phase 3] text2sql 전환            ← 개발자 B (병렬)
              · A: 인과 분석(AGE Cypher) + What-if
              · B: 벡터 검색(pgvector) + FK 조회

Week 5~7:   [Phase 4] analyzer 전환           ← A+B 합류
              · DDL 파싱 → Argus Catalog 직접 저장
              · 리니지 → Argus lineage 테이블
              · 메타 보강 → Catalog API 호출

Week 7~8:   [Phase 5] 통합 테스트 + 마이그레이션
              · E2E 테스트 (AGE + pgvector + Argus)
              · Neo4j 데이터 → AGE 마이그레이션
              · Docker 설정 정리

────────────────────────────────────────────────────
Week 8 완료: 프로덕션 배포 (화성정수장)
```

---

## 13. 정리

| 구성요소 | 역할 | 라이선스 |
|---------|------|---------|
| **Apache AGE** | 온톨로지 5계층 그래프 — 관계 정의·경로 탐색·인과 분석·What-if | Apache 2.0 |
| **pgvector** | 벡터 검색 — 테이블·컬럼·쿼리 시맨틱 검색 | PostgreSQL License |
| **Argus Catalog** | 범용 데이터 카탈로그 — 메타CRUD·표준사전·코드·품질·리니지 | 사내 |
| **Argus RAG Server** | 임베딩 파이프라인 — 벡터 임베딩 생성·관리 | 사내 |
| **PostgreSQL** | 단일 데이터베이스 인스턴스 — 위 모든 구성요소의 공통 기반 | PostgreSQL License |

온톨로지의 핵심 가치(5계층 관계 탐색)는 **Apache AGE가 전담**하고, 범용 카탈로그 기능은 **Argus가 그대로 제공**한다. 모든 것이 **하나의 PostgreSQL 인스턴스** 위에서 동작하며, **라이선스 비용은 0원**이다.
