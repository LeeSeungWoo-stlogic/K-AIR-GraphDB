# LLM 통합 테스트 결과 보고서

**작성일**: 2026-04-15  
**테스트 대상**: K-AIR-GraphDB (PostgreSQL + pgvector) × OpenAI API  
**LLM 모델**: gpt-4.1-mini (생성), text-embedding-3-small (임베딩)

---

## 1. 개요

K-AIR 서비스의 핵심 기능(시맨틱 검색, Text2SQL, 온톨로지 개념 추출)이 K-AIR-GraphDB와 OpenAI LLM 연동 하에 정상 동작하는지 검증하는 E2E 통합 테스트.

### 테스트 결과 요약

| 항목 | 결과 |
|------|------|
| 총 테스트 건수 | **9건** |
| 통과 | **9건 (100%)** |
| 실패 | 0건 |
| 소요 시간 | **12.73초** |
| LLM API | OpenAI (gpt-4.1-mini / text-embedding-3-small) |
| DB 대상 | K-AIR-GraphDB (localhost:15432) |

```
======================== 9 passed, 1 warning in 12.73s ========================
```

---

## 2. 테스트 구성

### 2.1 테스트 파일

`services/tests/test_e2e_llm_integration.py` — 4개 테스트 클래스, 9개 테스트 케이스

| 클래스 | 테스트 수 | 검증 대상 |
|--------|----------|----------|
| `TestLLMConnection` | 2 | OpenAI API 연결 + 임베딩 모델 가용성 |
| `TestEmbeddingPgvector` | 3 | 임베딩 생성 → pgvector 저장 → 시맨틱 검색 |
| `TestLLMGeneration` | 3 | LLM 기반 텍스트/SQL/온톨로지 생성 |
| `TestLLMCleanup` | 1 | 테스트 데이터 정리 |

---

## 3. 상세 테스트 결과

### 3.1 OpenAI API 연결 검증

#### test_api_key_valid
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 사용 가능 모델 수 | **120개** |
| 검증 방식 | `openai.models.list()` 호출 후 모델 목록 반환 확인 |

#### test_embedding_model_available
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 모델 | `text-embedding-3-small` |
| 임베딩 차원 | **1536차원** |
| 검증 방식 | "테스트" 텍스트 임베딩 생성 후 차원 수 확인 |

---

### 3.2 임베딩 + pgvector 시맨틱 검색

#### 테스트 데이터

5개 가상 테이블의 한국어 설명을 OpenAI 임베딩으로 변환하여 K-AIR-GraphDB의 `t2s_tables.vector` 컬럼에 저장:

| 테이블명 | 설명 |
|----------|------|
| `llm_e2e_users` | 사용자 계정 정보를 저장하는 테이블. 이메일, 이름, 가입일 포함. |
| `llm_e2e_orders` | 주문 내역 테이블. 주문일, 금액, 상태, 배송지 정보 포함. |
| `llm_e2e_products` | 상품 카탈로그 테이블. 상품명, 카테고리, 가격, 재고 수량 포함. |
| `llm_e2e_payments` | 결제 정보 테이블. 결제 수단, 금액, 승인번호, 결제일 포함. |
| `llm_e2e_reviews` | 상품 리뷰 테이블. 별점, 리뷰 내용, 작성자, 작성일 포함. |

#### test_generate_and_store_embeddings
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 저장 건수 | 5개 테이블 임베딩 |
| 벡터 차원 | 1536 |
| 저장 대상 | `t2s_tables.vector` (pgvector) |

#### test_semantic_search_order_related
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 질의 | "주문 금액과 결제 정보를 조회하고 싶습니다" |
| 검색 방식 | pgvector HNSW 코사인 유사도 (`vector <=> query::vector`) |

**검색 결과:**

| 순위 | 테이블 | 코사인 유사도 |
|------|--------|-------------|
| **1** | **llm_e2e_orders** | **0.6560** |
| **2** | **llm_e2e_payments** | **0.4761** |
| 3 | llm_e2e_users | 0.3291 |

주문(orders)과 결제(payments) 테이블이 Top-2로 정확하게 반환됨.

#### test_semantic_search_user_related
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 질의 | "회원 가입 정보와 이메일을 확인하고 싶습니다" |

**검색 결과:**

| 순위 | 테이블 | 코사인 유사도 |
|------|--------|-------------|
| **1** | **llm_e2e_users** | **0.4739** |

사용자(users) 테이블이 Top-1으로 정확하게 반환됨.

---

### 3.3 LLM 기반 텍스트/SQL/온톨로지 생성

#### test_table_description_generation
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 모델 | gpt-4.1-mini |
| 입력 | `order_id (INTEGER), user_id (INTEGER), order_date (TIMESTAMP), total_amount (DECIMAL), status (VARCHAR)` |
| 생성 결과 | "'orders' 테이블은 주문 ID, 사용자 ID, 주문 일시, 총 금액, 주문 상태 정보를 저장합니다." |

K-AIR-analyzer 서비스의 메타데이터 보강 기능(테이블 설명 자동 생성) 시뮬레이션 성공.

#### test_natural_language_to_sql
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 모델 | gpt-4.1-mini |
| 자연어 질문 | "지난 달 가입한 사용자 중 주문 금액이 10만원 이상인 사람의 이름과 총 주문 금액을 조회해줘" |

**생성된 SQL:**

```sql
SELECT u.name, SUM(o.total_amount) AS total_order_amount
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE u.created_at >= date_trunc('month', CURRENT_DATE - interval '1 month')
  AND u.created_at < date_trunc('month', CURRENT_DATE)
GROUP BY u.name
HAVING SUM(o.total_amount) >= 100000;
```

K-AIR-text2sql 서비스의 핵심 기능(자연어→SQL 변환) 시뮬레이션 성공. JOIN, GROUP BY, HAVING, date_trunc 등 PostgreSQL 고급 구문이 정확하게 생성됨.

#### test_ontology_concept_extraction
| 항목 | 결과 |
|------|------|
| 상태 | **PASSED** |
| 모델 | gpt-4.1-mini |
| 입력 문서 | K-Water 수처리 시스템 문서 (탁도, pH, 응집제, 잔류 염소 관련) |

**추출된 5-Layer 온톨로지 개념:**

| 계층 | 개념명 | 설명 (요약) |
|------|--------|------------|
| **DataSource** | 원수 탁도, 원수 pH, 잔류 염소 농도 | 실시간 측정 데이터 소스 |
| **Resource** | 응집제 | 화학 처리 자원 |
| **Process** | 응집제 투입 조절, 최종 수질 검사 | 수처리 프로세스 |
| **Measure** | 응집제 투입량, 잔류 염소 농도 | 정량 측정값 |
| **KPI** | 잔류 염소 농도 기준 충족 | 최종 품질 지표 |

5개 계층(KPI, Measure, Process, Resource, DataSource) 모두 포함된 온톨로지 개념이 추출됨. K-AIR-domain-layer 서비스의 핵심 기능(문서→온톨로지 개념 추출) 시뮬레이션 성공.

---

## 4. 검증 흐름 요약

```
OpenAI API 키 유효 → 임베딩 모델(1536차원) 확인
        │
        ▼
5개 테이블 설명 → text-embedding-3-small → 1536차원 벡터
        │
        ▼
K-AIR-GraphDB t2s_tables.vector에 INSERT (pgvector)
        │
        ▼
자연어 질의 → 임베딩 → pgvector HNSW cosine 검색 → 정확한 Top-K 반환
        │
        ▼
LLM 생성: 테이블 설명 / 자연어→SQL / 온톨로지 개념 추출 → 모두 성공
        │
        ▼
테스트 데이터 정리 (DELETE 5건)
```

---

## 5. K-AIR 서비스별 LLM 기능 매핑

| K-AIR 서비스 | LLM 기능 | 테스트 항목 | 결과 |
|---|---|---|---|
| **K-AIR-domain-layer** | 온톨로지 개념 추출 (5-Layer) | `test_ontology_concept_extraction` | PASSED |
| **K-AIR-text2sql** | 시맨틱 테이블 검색 (pgvector) | `test_semantic_search_*` (2건) | PASSED |
| **K-AIR-text2sql** | 자연어 → SQL 변환 | `test_natural_language_to_sql` | PASSED |
| **K-AIR-analyzer** | 테이블 설명 자동 생성 | `test_table_description_generation` | PASSED |

---

## 6. 결론

1. **OpenAI API 연결 정상**: API 키 유효, 120개 모델 사용 가능, 임베딩 모델 1536차원 확인.

2. **pgvector 시맨틱 검색 정확성 검증**: 5개 테이블 임베딩을 K-AIR-GraphDB에 저장한 후, 자연어 질의에 대해 의미적으로 가장 관련 있는 테이블이 Top-1으로 정확히 반환됨 (주문 질의→orders, 회원 질의→users).

3. **LLM 생성 품질 검증**: 테이블 설명 생성, 자연어→SQL 변환(JOIN/GROUP BY/HAVING 포함), 온톨로지 5-Layer 개념 추출 모두 기대 수준의 품질로 생성됨.

4. **K-AIR 서비스 전 기능 커버**: domain-layer(온톨로지), text2sql(시맨틱 검색 + SQL 생성), analyzer(메타데이터 보강) 3개 서비스의 LLM 의존 핵심 기능이 K-AIR-GraphDB 기반으로 정상 동작함을 확인.

**LLM 통합 테스트 9건 전체 PASSED — K-AIR-GraphDB + OpenAI 연동 검증 완료.**
