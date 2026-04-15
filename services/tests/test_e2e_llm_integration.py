"""E2E: LLM + K-AIR-GraphDB 통합 테스트

OpenAI API를 사용하여:
1. API 연결 검증
2. 임베딩 생성 → pgvector 저장 → 시맨틱 검색
3. LLM 기반 테이블 설명 생성
4. LLM 기반 자연어→SQL 변환 시뮬레이션
"""

import os
import json
import pytest
import asyncpg

GRAPHDB_DSN = "postgresql://kair:kair_pass@localhost:15432/kair_graphdb"

ENV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "repos", "KAIR", "robo-data-platform", ".env"
)


def _load_api_key() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return os.getenv("OPENAI_API_KEY")
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OPENAI_API_KEY=") and "your-" not in line:
                    return line.split("=", 1)[1]
    pytest.skip("OPENAI_API_KEY not found")


@pytest.fixture(scope="module")
def api_key():
    return _load_api_key()


@pytest.fixture(scope="module")
def openai_client(api_key):
    from openai import OpenAI
    return OpenAI(api_key=api_key)


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(GRAPHDB_DSN, min_size=2, max_size=5)
    yield pool
    await pool.close()


class TestLLMConnection:
    """OpenAI API 연결 검증"""

    def test_api_key_valid(self, openai_client):
        response = openai_client.models.list()
        model_ids = [m.id for m in response.data]
        assert len(model_ids) > 0
        print(f"\n  사용 가능 모델 수: {len(model_ids)}")

    def test_embedding_model_available(self, openai_client):
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input="테스트",
        )
        assert len(response.data) == 1
        assert len(response.data[0].embedding) == 1536
        print(f"\n  임베딩 차원: {len(response.data[0].embedding)}")


class TestEmbeddingPgvector:
    """임베딩 생성 → pgvector 저장 → 시맨틱 검색"""

    SAMPLE_TABLES = [
        {"name": "llm_e2e_users", "desc": "사용자 계정 정보를 저장하는 테이블. 이메일, 이름, 가입일 포함."},
        {"name": "llm_e2e_orders", "desc": "주문 내역 테이블. 주문일, 금액, 상태, 배송지 정보 포함."},
        {"name": "llm_e2e_products", "desc": "상품 카탈로그 테이블. 상품명, 카테고리, 가격, 재고 수량 포함."},
        {"name": "llm_e2e_payments", "desc": "결제 정보 테이블. 결제 수단, 금액, 승인번호, 결제일 포함."},
        {"name": "llm_e2e_reviews", "desc": "상품 리뷰 테이블. 별점, 리뷰 내용, 작성자, 작성일 포함."},
    ]

    async def test_generate_and_store_embeddings(self, openai_client, pg_pool):
        """임베딩을 생성하고 t2s_tables에 저장"""
        texts = [t["desc"] for t in self.SAMPLE_TABLES]
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        assert len(response.data) == 5

        async with pg_pool.acquire() as conn:
            for i, table in enumerate(self.SAMPLE_TABLES):
                vec = response.data[i].embedding
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                await conn.execute(
                    """INSERT INTO t2s_tables (db, schema_name, name, description, vector)
                       VALUES ($1, $2, $3, $4, $5::vector)
                       ON CONFLICT (db, schema_name, name) DO UPDATE
                         SET description = EXCLUDED.description, vector = EXCLUDED.vector""",
                    "llm_e2e", "public", table["name"], table["desc"], vec_str,
                )

            count = await conn.fetchval(
                "SELECT COUNT(*) FROM t2s_tables WHERE db = 'llm_e2e'"
            )
            assert count == 5
            print(f"\n  {count}개 테이블 임베딩 저장 완료")

    async def test_semantic_search_order_related(self, openai_client, pg_pool):
        """'주문 금액을 알고 싶다' → 가장 유사한 테이블 검색 (pgvector cosine)"""
        query = "주문 금액과 결제 정보를 조회하고 싶습니다"
        resp = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        q_vec = resp.data[0].embedding
        q_vec_str = "[" + ",".join(str(v) for v in q_vec) + "]"

        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT name, description,
                          1 - (vector <=> $1::vector) AS similarity
                   FROM t2s_tables
                   WHERE db = 'llm_e2e' AND vector IS NOT NULL
                   ORDER BY vector <=> $1::vector
                   LIMIT 3""",
                q_vec_str,
            )
            assert len(rows) >= 2
            top_names = [r["name"] for r in rows]
            print(f"\n  질의: '{query}'")
            for r in rows:
                print(f"    {r['name']}: similarity={r['similarity']:.4f}")

            assert any("orders" in n for n in top_names) or any("payments" in n for n in top_names), \
                f"주문/결제 관련 테이블이 상위에 없음: {top_names}"

    async def test_semantic_search_user_related(self, openai_client, pg_pool):
        """'회원 정보' → users 테이블이 최상위"""
        query = "회원 가입 정보와 이메일을 확인하고 싶습니다"
        resp = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        q_vec = resp.data[0].embedding
        q_vec_str = "[" + ",".join(str(v) for v in q_vec) + "]"

        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT name, 1 - (vector <=> $1::vector) AS similarity
                   FROM t2s_tables
                   WHERE db = 'llm_e2e' AND vector IS NOT NULL
                   ORDER BY vector <=> $1::vector
                   LIMIT 1""",
                q_vec_str,
            )
            print(f"\n  질의: '{query}'")
            print(f"    Top-1: {row['name']} (similarity={row['similarity']:.4f})")
            assert "users" in row["name"], f"users 테이블이 아닌 {row['name']}이 Top-1"


class TestLLMGeneration:
    """LLM 기반 텍스트/SQL 생성"""

    def test_table_description_generation(self, openai_client):
        """LLM으로 테이블 컬럼 기반 설명 생성"""
        columns = "order_id (INTEGER), user_id (INTEGER), order_date (TIMESTAMP), total_amount (DECIMAL), status (VARCHAR)"
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "당신은 데이터베이스 전문가입니다. 테이블의 컬럼 정보를 보고 간결한 한국어 설명을 생성하세요."},
                {"role": "user", "content": f"다음 컬럼을 가진 'orders' 테이블을 한 문장으로 설명하세요:\n{columns}"},
            ],
            max_tokens=200,
        )
        desc = response.choices[0].message.content
        assert len(desc) > 10
        print(f"\n  생성된 설명: {desc}")

    def test_natural_language_to_sql(self, openai_client):
        """자연어 질문 → SQL 변환"""
        schema_context = """
        테이블: users (id, name, email, created_at)
        테이블: orders (id, user_id, order_date, total_amount, status)
        테이블: products (id, name, category, price)
        """
        question = "지난 달 가입한 사용자 중 주문 금액이 10만원 이상인 사람의 이름과 총 주문 금액을 조회해줘"

        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "당신은 Text-to-SQL 전문가입니다. 주어진 스키마를 참고하여 PostgreSQL SELECT 쿼리를 생성하세요. SQL만 출력하세요."},
                {"role": "user", "content": f"스키마:\n{schema_context}\n\n질문: {question}"},
            ],
            max_tokens=500,
        )
        sql = response.choices[0].message.content
        assert "SELECT" in sql.upper()
        assert "users" in sql.lower() or "orders" in sql.lower()
        print(f"\n  질문: {question}")
        print(f"  생성 SQL:\n{sql}")

    def test_ontology_concept_extraction(self, openai_client):
        """LLM으로 온톨로지 개념 추출 (K-AIR domain-layer 핵심 기능)"""
        document = """
        K-Water 수처리 시스템에서는 원수의 탁도와 pH를 실시간 모니터링합니다.
        정수장의 응집제 투입량은 탁도에 따라 자동 조절되며,
        최종 수질 검사에서 잔류 염소 농도가 기준치를 충족해야 합니다.
        """
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": (
                    "당신은 온톨로지 설계 전문가입니다. 주어진 문서에서 5-Layer 온톨로지 개념을 추출하세요.\n"
                    "계층: KPI, Measure, Process, Resource, DataSource\n"
                    "JSON 배열로 출력하세요: [{\"layer\": \"...\", \"name\": \"...\", \"description\": \"...\"}]"
                )},
                {"role": "user", "content": document},
            ],
            max_tokens=800,
        )
        content = response.choices[0].message.content
        json_start = content.find("[")
        json_end = content.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            concepts = json.loads(content[json_start:json_end])
            assert len(concepts) >= 3
            layers = set(c["layer"] for c in concepts)
            print(f"\n  추출 개념 수: {len(concepts)}")
            print(f"  계층: {layers}")
            for c in concepts[:5]:
                print(f"    [{c['layer']}] {c['name']}: {c.get('description', '')[:50]}")
        else:
            assert False, f"JSON 파싱 실패: {content[:200]}"


class TestLLMCleanup:
    """LLM 테스트 데이터 정리"""

    async def test_cleanup(self, pg_pool):
        async with pg_pool.acquire() as conn:
            deleted = await conn.execute(
                "DELETE FROM t2s_tables WHERE db = 'llm_e2e'"
            )
            print(f"\n  LLM E2E 테스트 데이터 정리 완료: {deleted}")
