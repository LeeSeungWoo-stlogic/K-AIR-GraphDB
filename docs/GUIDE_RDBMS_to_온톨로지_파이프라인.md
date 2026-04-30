# 프로젝트 가이드: RDBMS-to-Ontology 지식 그래프 구축 파이프라인

## 1. 프로젝트 개요

이 프로젝트는 **이기종 RDBMS의 물리적 스키마 정보**와 **비정형 문서에서 추출한 비즈니스 온톨로지**를 결합하여, 데이터의 **물리적 위치**와 **비즈니스 의미**를 연결하는 **다층 지식 그래프(Multi-layer Knowledge Graph)** 를 구축하는 것을 목표로 한다.

아래 **4단계 워크플로**는 설계 관점의 전체 골격이며, **Step 1**은 현재 저장소(`K_Water_v1`)에서 `meta_ingest_proto`·`physical_meta` 기준으로 구현 대응을 상세히 적는다. Step 2~4는 로드맵·요구사항으로 정리하고, 저장소 내 연계 지점이 있으면 괄호로 표시한다.

---

## 2. 4단계 구축 프로세스 (Workflow)

### Step 1: 물리 메타데이터 추출 및 그래프 노드화 (Physical Layer)

#### 설계 상 대상·작업

| 항목 | 내용 |
|------|------|
| **대상** | 보유 중인 이기종 DB (Oracle, Tibero, PostgreSQL 등) |
| **작업** | 연결 핸들러(Host, ID, PW, SID/DB Name 등)를 이용한 **메타데이터 추출 스크립트** 실행 |
| **추출 항목** | Table명, Column명, 데이터 타입, Foreign Key 관계, Table/Column Comment(설명) |
| **그래프 구조 (목표 모델)** | `Database`, `Table`, `Column` 을 **개별 노드**로 두고, `HAS_TABLE`, `HAS_COLUMN`, `REFERENCES(FK)` 등의 관계(Edge) 정의 |

#### 저장소 구현과의 대응 (Step 1)

카탈로그 추출 이후 흐름:

```text
[이기종 RDBMS] --(카탈로그 추출)--> [Canonical Catalog JSON]
        |
        +--> [RDB 메타 적재: t2s_tables / t2s_columns / t2s_fk_constraints]  (GraphDB 내 PostgreSQL 테이블)
        |
        +--> [AGE 물리층: :Database / :Table / :Column / HAS_TABLE / HAS_COLUMN / FK_TO]  (ontology_graph)
```

- **물리층**: 스키마·테이블·컬럼·FK·코멘트 등 RDB가 직접 알려 주는 사실만 그래프화한다.

**엔진별 추출기 (`SOURCE_ENGINE`)**

| 엔진 | `meta_ingest` 구현 상태 (요약) |
|------|--------------------------------|
| **PostgreSQL** | `information_schema` + `pg_catalog` 기반 **실추출** (`services/meta_ingest_proto/meta_ingest/adapters/postgres.py`). |
| **Oracle / MySQL / Tibero** | 추출기 팩토리·클래스 연결은 있으나 **실추출은 골격·`NotImplementedError`** 단계. 동일 카탈로그 JSON 계약을 채우는 SQL·드라이버 보강 필요. |

**연결 정보 (Postgres 기준 환경 변수)**

| 역할 | 변수 (예) |
|------|-----------|
| 호스트/포트 | `SOURCE_PG_HOST`, `SOURCE_PG_PORT` |
| 계정 | `SOURCE_PG_USER`, `SOURCE_PG_PASSWORD` |
| DB 이름 / 스키마 | `SOURCE_PG_DB`, `SOURCE_PG_SCHEMA` |
| 엔진 선택 | `SOURCE_ENGINE` (기본 `postgres`) |

GraphDB 타깃: `TARGET_PG_*` , 논리 데이터소스 라벨: `META_DB_LABEL` (`t2s_tables.db`, `:Table`·`:Column`의 `datasource`, `fqn` 접두. **물리 DB 이름과 다를 수 있음**).

**실행:** `services/meta_ingest_proto` 에서 `python ingest.py run` 또는 `extract` 후 `load` (`PYTHONPATH`에 리포 `libs`).

**추출 항목 ↔ 구현 매핑**

| 추출 항목 | 카탈로그/그래프 표현 (요약) |
|-----------|-----------------------------|
| Table 명 | `tables[].name`, AGE `:Table.name` |
| Column 명 | `tables[].columns[].column_name`, AGE `:Column.name` |
| 데이터 타입 | Postgres: `data_type`, `udt_name`, 길이/정밀도 등 → 문자열 `dtype` |
| Foreign Key | `foreign_keys[]`; AGE에서는 컬럼 간 관계 (아래 표) |
| Table / Column Comment | Table `description`, Column `description` (`pg_description` 등) |

**코드 위치:** `libs/age_graph_repository/physical_meta/physical_cypher.py` (`build_physical_meta_refresh`), `services/meta_ingest_proto/meta_ingest/sinks/t2s.py`, `sinks/age_psycopg.py`.

**논리 식별자 옵션 B (합의)**

| 필드 | 규칙 |
|------|------|
| `meta_db_label` | **짧은 논리 데이터소스 ID**만 담는다. **엔진 종류·도커 컨테이너명은 넣지 않는다.** 문법: 소문자·숫자·밑줄만 `^[a-z0-9_]+$` (`validate_catalog_for_ingest`). |
| `source_engine` | `postgres` \| `oracle` \| … — 기술적 엔진 구분은 **항상 이 필드**로만 본다. |
| `catalog.source` | 추적용 **호스트·포트·dbname** 만 허용. **계정·비밀번호·토큰 등은 저장하지 않는다** (`strip_secrets_from_source`). |

`_physical_vertex_id` 패턴: `meta_ingest:D:{meta_db_label}` / `T` / `C` … (세부는 `physical_meta.models`).

**AGE 적재 정책 (스냅샷 치환)**

동일 `meta_db_label`에 대해 `_meta_ingest = true` 인 **Column → Table → Database**(해당 라벨) 순 **삭제 후**, `Database` 1개 생성 → 각 `Table` · `HAS_TABLE` · `Column(s)` · `HAS_COLUMN` · `FK_TO` 를 **전부 재생성**한다. 행 단위 `MERGE` 갱신이 아니라 **멱등한 전체 치환**(정합성·구현 단순화 우선). 규모·SLA가 커지면 증분 전략을 별도 검토한다.

**운영 추적**

- 추출 직후: `meta_ingest.catalog_validate.validate_catalog_for_ingest`
- 인제스트 stdout: `ingest_audit:` 한 줄(비밀 없음) + `t2s`/`AGE` 건수(`Database`, `HAS_TABLE` 포함)
- 적재 후 AGE 샘플: `services/meta_ingest_proto/scripts/verify_age_physical_database.sql`

##### 목표 그래프 용어와 AGE 라벨 (구현 반영)

| 설계(가이드) | 현재 구현 (`ontology_graph`) |
|--------------|------------------------------|
| **`Database` 노드** | **`(:Database)`** 속성: `meta_db_label`, `source_engine`, `_meta_ingest`, `_physical_vertex_id` |
| **`HAS_TABLE`** | **`(:Database)-[:HAS_TABLE]->(:Table)`** (빈 속성 맵) |
| **`HAS_COLUMN`** | **`(:Table)-[:HAS_COLUMN]->(:Column)`** |
| **REFERENCES(FK)** | **`(:Column)-[:FK_TO {constraint, position}]->(:Column)`** |
| **테이블 스코프 속성** | `:Table.datasource` 는 **옵션 B와 동일하게 `meta_db_label`** 를 유지(필터 편의·기존 `fqn` 규칙과 일치). |

물리 계약 버전: **`PHYSICAL_META_CONTRACT_VERSION` = `1.1.0`** (`Database`·`HAS_TABLE` 도입).

---

### Step 2: 비정형 문서 기반 비즈니스 온톨로지 추출 (Semantic Layer)

| 항목 | 내용 |
|------|------|
| **대상** | 비정형 문서 자료 (보고서, 지침서, 매뉴얼 등) |
| **작업** | AI(LLM)를 활용하여 아래 **5계층** 요소를 선별·구조화 |
| **계층** | **KPI** → **Measure** → **Driver** → **Process** → **Resource** (핵심 성과 지표, 측정 항목/수치, 동인·영향 요인, 업무 프로세스, 투입 자원) |
| **그래프 구조** | 비즈니스 인과·계층에 따른 노드 및 엣지 생성 |

**저장소:** 본 레포에서는 전용 적재 파이프라인이 Step 1과 분리되어 있을 수 있다. 문서·LLM 추출본은 Step 3 매핑을 위해 **동일 GraphDB 또는 별도 스키마**에 적재한다는 전제로 설계한다.

---

### Step 3: AI 기반 레이어 간 매핑 (Cross-Layer Mapping)

| 항목 | 내용 |
|------|------|
| **작업** | Step 1 **물리 노드**와 Step 2 **비즈니스 노드** 간 연관성 분석 |
| **매핑 로직** | Column Comment와 비즈니스 용어 간 **시맨틱 유사도**; SQL 쿼리 로그·데이터 정의서를 바탕으로 **`MAPPED_TO`**(또는 동등 개념) 관계 생성 |
| **목적** | “어떤 비즈니스 지표(KPI)가 실제 어느 DB의 어느 테이블에서 계산되는가?” 경로 확보 |

**저장소:** 관계 타입·프로퍼티 명은 구현 시 Cypher 계약으로 고정하는 것을 권장. 물리층은 `fqn`, `_physical_vertex_id` 등으로 앵커 가능.

---

### Step 4: 통합 그래프 아키텍처 완성 (Final Architecture)

| 항목 | 내용 |
|------|------|
| **결과물** | 두 종류 서브그래프가 통합된 이기종 지식 그래프 |
| **Layer A (Physical)** | DB 인벤토리 및 스키마 구조 그래프 (Step 1) |
| **Layer B (Business)** | 도메인 지식 및 의사결정 체계 그래프 (Step 2) |
| **연결** | 두 레이어는 AI가 생성한 **매핑 엣지**(Step 3)로 브릿지 |

---

## 3. IDE·AI를 위한 개발 컨텍스트

| 항목 | 내용 |
|------|------|
| **기술 스택** | Python, **Apache AGE**(그래프 레이어; Neo4j 병행·이력은 별도 이관 스크립트 참고), LLM(추출/매핑), 메타 추출은 **psycopg** 등 엔진별 클라이언트 (`SQLAlchemy`는 선택) |
| **구현 시 고려** | 이기종 DB 핸들러는 **추상 인터페이스**로 설계 (`CatalogExtractor` 팩토리 방향) |
| | AI 추출 시 **할루시네이션 방지**를 위해 스키마·카탈로그 기반 제약(Constraints) 활용 |
| | 그래프 적재 전 **데이터 정합성 검증** 단계 포함 |

---

## 4. AI 요청 예시 (복사용)

- Step 1: “PostgreSQL과 Oracle에서 테이블·컬럼 메타데이터를 추출해 **동일 JSON 스키마**(카탈로그)로 만드는 Python 모듈을 작성해 줘. Oracle은 `ALL_TABLES` / `ALL_TAB_COLUMNS` / `ALL_CONSTRAINTS` 를 가정해 줘.”
- Step 3: “Step 2의 KPI 노드와 Step 1의 `:Column` 노드를 유사도 기반으로 잇는 **`MAPPED_TO` 제안 Cypher** 를 작성해 줘. 물리층은 `fqn` 또는 `datasource`+`schema`+`name` 으로 필터해 줘.”

---

## 5. 산출물·추적성 (저장소)

| 산출물 | 경로 |
|--------|------|
| 물리 계약·Cypher 빌더 | `libs/age_graph_repository/physical_meta/` |
| 인제스트 CLI·어댑터·싱크 | `services/meta_ingest_proto/meta_ingest/` |
| 계약 버전 | `PHYSICAL_META_CONTRACT_VERSION` (카탈로그 `contract_version`과 연계) |

---

## 6. 문서 유지

- 본 파일은 **전체 4단계 가이드**와 **Step 1 구현 대응**을 한 장에 둔다.
- 상충 시 **실제 코드**와 `services/meta_ingest_proto/README.md`를 우선한다.
- 원본 논의 초안은 `docs/guide_rdbms_ontology.md` 에 보관할 수 있으며, **단일 통합본은 본 파일**을 기준으로 갱신한다.
- **Step 1 완료 검증·경로 인덱스·이기종 목업 범위**는 `docs/step1_completion_bundle/` 에 정리한다.
