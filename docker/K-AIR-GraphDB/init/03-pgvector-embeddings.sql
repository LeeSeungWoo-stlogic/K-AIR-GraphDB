-- ============================================================
-- P1-05: pgvector 임베딩 테이블 + HNSW 인덱스
-- text2sql 벡터 검색, 테이블/컬럼/쿼리 시맨틱 검색용
-- ============================================================

-- 1) 테이블 임베딩 (catalog_datasets와 1:1 대응 가능)
CREATE TABLE IF NOT EXISTS embedding_tables (
    id              TEXT PRIMARY KEY,
    dataset_name    TEXT NOT NULL,
    schema_name     TEXT,
    description     TEXT,
    embedding       vector(1536),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_tables_hnsw
    ON embedding_tables
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_embedding_tables_name
    ON embedding_tables (dataset_name);

COMMENT ON TABLE embedding_tables IS
    'pgvector 기반 테이블 임베딩 — text2sql 시맨틱 검색용';

-- 2) 컬럼 임베딩
CREATE TABLE IF NOT EXISTS embedding_columns (
    id              TEXT PRIMARY KEY,
    table_id        TEXT REFERENCES embedding_tables(id) ON DELETE CASCADE,
    column_name     TEXT NOT NULL,
    data_type       TEXT,
    description     TEXT,
    embedding       vector(1536),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_columns_hnsw
    ON embedding_columns
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_embedding_columns_table
    ON embedding_columns (table_id);

COMMENT ON TABLE embedding_columns IS
    'pgvector 기반 컬럼 임베딩 — text2sql 시맨틱 검색용';

-- 3) 쿼리 임베딩 (T2S 쿼리 캐시 + 유사 쿼리 검색)
CREATE TABLE IF NOT EXISTS embedding_queries (
    id              TEXT PRIMARY KEY,
    natural_query   TEXT NOT NULL,
    sql_query       TEXT,
    embedding       vector(1536),
    execution_count INTEGER DEFAULT 1,
    last_used_at    TIMESTAMPTZ DEFAULT now(),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_queries_hnsw
    ON embedding_queries
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

COMMENT ON TABLE embedding_queries IS
    'pgvector 기반 쿼리 임베딩 — text2sql 유사 쿼리 캐시/검색용';

-- 4) 온톨로지 노드 임베딩 (AGE 노드와 연계)
CREATE TABLE IF NOT EXISTS embedding_ontology_nodes (
    id              TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    node_name       TEXT,
    node_label      TEXT,
    description     TEXT,
    embedding       vector(1536),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_embedding_ontology_hnsw
    ON embedding_ontology_nodes
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_embedding_ontology_node_id
    ON embedding_ontology_nodes (node_id);

COMMENT ON TABLE embedding_ontology_nodes IS
    'pgvector 기반 온톨로지 노드 임베딩 — 시맨틱 노드 검색 + AGE 연계';
