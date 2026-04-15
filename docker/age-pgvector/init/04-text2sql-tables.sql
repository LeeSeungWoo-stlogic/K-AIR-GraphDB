-- ============================================================
-- P3-DDL: text2sql 서비스용 PostgreSQL 테이블 + pgvector 인덱스
-- Neo4j의 Fabric_Table/Column, T2S_Query/ValueMapping 노드와
-- HAS_COLUMN, FK_TO, USES_TABLE 등 관계를 RDB로 전환.
-- ============================================================

-- 1) 테이블 메타데이터 (replaces :Fabric_Table nodes)
CREATE TABLE IF NOT EXISTS t2s_tables (
    id                  SERIAL PRIMARY KEY,
    db                  TEXT NOT NULL DEFAULT '',
    schema_name         TEXT NOT NULL DEFAULT '',
    name                TEXT NOT NULL,
    original_name       TEXT,
    description         TEXT DEFAULT '',
    analyzed_description TEXT DEFAULT '',
    comment             TEXT DEFAULT '',
    text_to_sql_embedding_text TEXT DEFAULT '',
    text_to_sql_is_valid BOOLEAN DEFAULT true,
    vector              vector(1536),
    text_to_sql_vector  vector(1536),
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (db, schema_name, name)
);

CREATE INDEX IF NOT EXISTS idx_t2s_tables_name
    ON t2s_tables (name);
CREATE INDEX IF NOT EXISTS idx_t2s_tables_schema_name
    ON t2s_tables (schema_name, name);

CREATE INDEX IF NOT EXISTS idx_t2s_tables_vec_hnsw
    ON t2s_tables
    USING hnsw (vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_t2s_tables_t2s_vec_hnsw
    ON t2s_tables
    USING hnsw (text_to_sql_vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

COMMENT ON TABLE t2s_tables IS
    'text2sql 서비스 — 테이블 메타데이터 + 벡터 임베딩 (Neo4j Fabric_Table 대체)';

-- 2) 컬럼 메타데이터 (replaces :Fabric_Column nodes + :HAS_COLUMN relationship)
CREATE TABLE IF NOT EXISTS t2s_columns (
    id                  SERIAL PRIMARY KEY,
    table_id            INTEGER NOT NULL REFERENCES t2s_tables(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    fqn                 TEXT UNIQUE,
    dtype               TEXT DEFAULT '',
    nullable            BOOLEAN DEFAULT true,
    description         TEXT DEFAULT '',
    is_primary_key      BOOLEAN DEFAULT false,
    enum_values         TEXT DEFAULT '',
    cardinality         INTEGER,
    text_to_sql_is_valid BOOLEAN DEFAULT true,
    vector              vector(1536),
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t2s_columns_table_id
    ON t2s_columns (table_id);
CREATE INDEX IF NOT EXISTS idx_t2s_columns_name
    ON t2s_columns (name);
CREATE INDEX IF NOT EXISTS idx_t2s_columns_fqn
    ON t2s_columns (fqn);

CREATE INDEX IF NOT EXISTS idx_t2s_columns_vec_hnsw
    ON t2s_columns
    USING hnsw (vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

COMMENT ON TABLE t2s_columns IS
    'text2sql 서비스 — 컬럼 메타데이터 + 벡터 임베딩 (Neo4j Fabric_Column + HAS_COLUMN 대체)';

-- 3) FK 관계 (replaces :FK_TO relationship between columns)
CREATE TABLE IF NOT EXISTS t2s_fk_constraints (
    id                  SERIAL PRIMARY KEY,
    from_column_id      INTEGER NOT NULL REFERENCES t2s_columns(id) ON DELETE CASCADE,
    to_column_id        INTEGER NOT NULL REFERENCES t2s_columns(id) ON DELETE CASCADE,
    constraint_name     TEXT DEFAULT '',
    UNIQUE (from_column_id, to_column_id)
);

CREATE INDEX IF NOT EXISTS idx_t2s_fk_from
    ON t2s_fk_constraints (from_column_id);
CREATE INDEX IF NOT EXISTS idx_t2s_fk_to
    ON t2s_fk_constraints (to_column_id);

COMMENT ON TABLE t2s_fk_constraints IS
    'text2sql 서비스 — 컬럼 간 FK 관계 (Neo4j FK_TO relationship 대체)';

-- 4) 쿼리 히스토리 + 캐시 (replaces :T2S_Query nodes)
CREATE TABLE IF NOT EXISTS t2s_queries (
    id                  TEXT PRIMARY KEY,
    question            TEXT NOT NULL,
    question_norm       TEXT DEFAULT '',
    sql_text            TEXT,
    status              TEXT DEFAULT 'completed',
    row_count           INTEGER,
    execution_time_ms   FLOAT,
    steps_count         INTEGER,
    error_message       TEXT,
    steps_summary       TEXT DEFAULT '',
    tables_used         TEXT[] DEFAULT '{}',
    columns_used        TEXT[] DEFAULT '{}',
    seen_count          INTEGER DEFAULT 1,
    verified            BOOLEAN DEFAULT false,
    verified_confidence FLOAT,
    verified_confidence_avg FLOAT,
    verified_source     TEXT DEFAULT '',
    quality_gate_json   TEXT DEFAULT '',
    value_mappings_count INTEGER DEFAULT 0,
    value_mapping_terms TEXT[] DEFAULT '{}',
    best_run_at_ms      BIGINT,
    best_context_score  FLOAT,
    best_context_steps_features TEXT DEFAULT '',
    best_context_steps_summary TEXT DEFAULT '',
    best_context_run_at_ms BIGINT,
    vector_question     vector(1536),
    vector_intent       vector(1536),
    created_at          TIMESTAMPTZ DEFAULT now(),
    created_at_ms       BIGINT,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    updated_at_ms       BIGINT,
    last_seen_at        TIMESTAMPTZ DEFAULT now(),
    last_seen_at_ms     BIGINT,
    verified_at         TIMESTAMPTZ,
    verified_at_ms      BIGINT
);

CREATE INDEX IF NOT EXISTS idx_t2s_queries_question
    ON t2s_queries (question);
CREATE INDEX IF NOT EXISTS idx_t2s_queries_created
    ON t2s_queries (created_at);
CREATE INDEX IF NOT EXISTS idx_t2s_queries_status
    ON t2s_queries (status);

CREATE INDEX IF NOT EXISTS idx_t2s_queries_question_vec_hnsw
    ON t2s_queries
    USING hnsw (vector_question vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_t2s_queries_intent_vec_hnsw
    ON t2s_queries
    USING hnsw (vector_intent vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

COMMENT ON TABLE t2s_queries IS
    'text2sql 서비스 — 쿼리 히스토리 + 벡터 유사도 캐시 (Neo4j T2S_Query 대체)';

-- 5) 쿼리 → 테이블 사용 관계 (replaces :USES_TABLE relationship)
CREATE TABLE IF NOT EXISTS t2s_query_table_usage (
    query_id            TEXT NOT NULL REFERENCES t2s_queries(id) ON DELETE CASCADE,
    table_id            INTEGER NOT NULL REFERENCES t2s_tables(id) ON DELETE CASCADE,
    PRIMARY KEY (query_id, table_id)
);

COMMENT ON TABLE t2s_query_table_usage IS
    'text2sql 서비스 — 쿼리-테이블 사용 관계 (Neo4j USES_TABLE 대체)';

-- 6) 쿼리 → 컬럼 사용 관계 (replaces :SELECTS/:FILTERS/:AGGREGATES/:GROUPS_BY/:JOINS_ON)
CREATE TABLE IF NOT EXISTS t2s_query_column_usage (
    query_id            TEXT NOT NULL REFERENCES t2s_queries(id) ON DELETE CASCADE,
    column_id           INTEGER NOT NULL REFERENCES t2s_columns(id) ON DELETE CASCADE,
    usage_type          TEXT NOT NULL DEFAULT 'SELECTS',
    PRIMARY KEY (query_id, column_id, usage_type)
);

CREATE INDEX IF NOT EXISTS idx_t2s_qcu_type
    ON t2s_query_column_usage (usage_type);

COMMENT ON TABLE t2s_query_column_usage IS
    'text2sql 서비스 — 쿼리-컬럼 사용 관계 (Neo4j SELECTS/FILTERS/... 대체)';

-- 7) 값 매핑 (replaces :T2S_ValueMapping nodes + :MAPS_TO relationship)
CREATE TABLE IF NOT EXISTS t2s_value_mappings (
    id                  SERIAL PRIMARY KEY,
    natural_value       TEXT NOT NULL,
    code_value          TEXT NOT NULL,
    column_id           INTEGER REFERENCES t2s_columns(id) ON DELETE SET NULL,
    column_fqn          TEXT,
    usage_count         INTEGER DEFAULT 1,
    verified            BOOLEAN DEFAULT false,
    verified_confidence FLOAT,
    verified_source     TEXT DEFAULT '',
    verified_at         TIMESTAMPTZ,
    verified_at_ms      BIGINT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (natural_value, column_fqn)
);

CREATE INDEX IF NOT EXISTS idx_t2s_vm_natural
    ON t2s_value_mappings (natural_value);
CREATE INDEX IF NOT EXISTS idx_t2s_vm_column_fqn
    ON t2s_value_mappings (column_fqn);
CREATE INDEX IF NOT EXISTS idx_t2s_vm_column_id
    ON t2s_value_mappings (column_id);

COMMENT ON TABLE t2s_value_mappings IS
    'text2sql 서비스 — 값 매핑 (자연어→코드) (Neo4j T2S_ValueMapping + MAPS_TO 대체)';
