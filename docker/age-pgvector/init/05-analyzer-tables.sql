-- =============================================================================
-- 05-analyzer-tables.sql
-- Analyzer 서비스 Neo4j 대체 PostgreSQL 테이블 DDL
-- Neo4j Labels: Analyzer_Table, Analyzer_Column, Analyzer_Schema, Analyzer_DataSource,
--               Analyzer_Procedure, Analyzer_Function, Analyzer_Trigger,
--               Analyzer_ETLProcess, Analyzer_UserStory, Analyzer_AcceptanceCriteria,
--               Glossary, Term, Domain, Owner, Tag,
--               BusinessCalendar, NonBusinessDay, Holiday
--               + 동적 AST 노드 (Labels.prefixed)
-- =============================================================================

-- 1) 데이터소스
CREATE TABLE IF NOT EXISTS analyzer_data_sources (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    source          TEXT DEFAULT 'ddl_ingestion',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 2) 스키마
CREATE TABLE IF NOT EXISTS analyzer_schemas (
    id              SERIAL PRIMARY KEY,
    db              TEXT NOT NULL,
    name            TEXT NOT NULL,
    datasource      TEXT DEFAULT '',
    UNIQUE(db, name)
);

CREATE TABLE IF NOT EXISTS analyzer_schema_datasource (
    schema_id       INT NOT NULL REFERENCES analyzer_schemas(id) ON DELETE CASCADE,
    datasource_id   INT NOT NULL REFERENCES analyzer_data_sources(id) ON DELETE CASCADE,
    PRIMARY KEY (schema_id, datasource_id)
);

-- 3) 테이블 메타데이터 (replaces :Analyzer_Table nodes)
CREATE TABLE IF NOT EXISTS analyzer_tables (
    id                  SERIAL PRIMARY KEY,
    db                  TEXT NOT NULL,
    schema_name         TEXT NOT NULL DEFAULT 'public',
    name                TEXT NOT NULL,
    description         TEXT DEFAULT '',
    description_source  TEXT DEFAULT '',
    analyzed_description TEXT DEFAULT '',
    table_type          TEXT DEFAULT 'BASE TABLE',
    datasource          TEXT DEFAULT '',
    cube_name           TEXT DEFAULT '',
    embedding           vector(1536),
    extra_props         JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE(db, schema_name, name)
);

CREATE INDEX IF NOT EXISTS idx_analyzer_tables_name ON analyzer_tables(name);
CREATE INDEX IF NOT EXISTS idx_analyzer_tables_schema ON analyzer_tables(schema_name);
CREATE INDEX IF NOT EXISTS idx_analyzer_tables_datasource ON analyzer_tables(datasource);
CREATE INDEX IF NOT EXISTS idx_analyzer_tables_embedding_hnsw
    ON analyzer_tables USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 4) 컬럼 메타데이터 (replaces :Analyzer_Column nodes)
CREATE TABLE IF NOT EXISTS analyzer_columns (
    id                  SERIAL PRIMARY KEY,
    fqn                 TEXT NOT NULL UNIQUE,
    table_id            INT REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    dtype               TEXT DEFAULT '',
    description         TEXT DEFAULT '',
    description_source  TEXT DEFAULT '',
    analyzed_description TEXT DEFAULT '',
    nullable            BOOLEAN DEFAULT TRUE,
    is_primary_key      BOOLEAN DEFAULT FALSE,
    pk_constraint       TEXT DEFAULT '',
    datasource          TEXT DEFAULT '',
    embedding           vector(1536),
    extra_props         JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyzer_columns_table ON analyzer_columns(table_id);
CREATE INDEX IF NOT EXISTS idx_analyzer_columns_name ON analyzer_columns(name);
CREATE INDEX IF NOT EXISTS idx_analyzer_columns_embedding_hnsw
    ON analyzer_columns USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 5) 테이블 간 관계 (replaces FK_TO_TABLE, FK_TO_COLUMN, ONE_TO_ONE, etc.)
CREATE TABLE IF NOT EXISTS analyzer_table_relationships (
    id                  SERIAL PRIMARY KEY,
    from_table_id       INT NOT NULL REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    to_table_id         INT NOT NULL REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    rel_type            TEXT NOT NULL DEFAULT 'FK_TO_TABLE',
    source_column       TEXT DEFAULT '',
    target_column       TEXT DEFAULT '',
    source              TEXT DEFAULT 'ddl',
    description         TEXT DEFAULT '',
    rel_subtype         TEXT DEFAULT 'many_to_one',
    similarity          REAL DEFAULT 0,
    match_ratio         REAL DEFAULT 0,
    matched_count       INT DEFAULT 0,
    total_samples       INT DEFAULT 0,
    extra_props         JSONB DEFAULT '{}',
    UNIQUE(from_table_id, to_table_id, rel_type, source_column, target_column)
);

CREATE INDEX IF NOT EXISTS idx_analyzer_trel_from ON analyzer_table_relationships(from_table_id);
CREATE INDEX IF NOT EXISTS idx_analyzer_trel_to ON analyzer_table_relationships(to_table_id);
CREATE INDEX IF NOT EXISTS idx_analyzer_trel_type ON analyzer_table_relationships(rel_type);

-- 6) 컬럼 간 FK 관계 (replaces FK_TO_COLUMN relationship)
CREATE TABLE IF NOT EXISTS analyzer_column_relationships (
    id                  SERIAL PRIMARY KEY,
    from_column_id      INT NOT NULL REFERENCES analyzer_columns(id) ON DELETE CASCADE,
    to_column_id        INT NOT NULL REFERENCES analyzer_columns(id) ON DELETE CASCADE,
    rel_type            TEXT NOT NULL DEFAULT 'FK_TO_COLUMN',
    source              TEXT DEFAULT 'ddl',
    similarity          REAL DEFAULT 0,
    match_ratio         REAL DEFAULT 0,
    matched_count       INT DEFAULT 0,
    total_samples       INT DEFAULT 0,
    UNIQUE(from_column_id, to_column_id, rel_type)
);

-- 7) AST 노드 (replaces dynamically-labeled Analyzer_* AST nodes)
CREATE TABLE IF NOT EXISTS analyzer_ast_nodes (
    id              SERIAL PRIMARY KEY,
    node_type       TEXT NOT NULL,
    name            TEXT DEFAULT '',
    file_name       TEXT DEFAULT '',
    directory       TEXT DEFAULT '',
    start_line      INT,
    end_line        INT,
    parent_id       INT REFERENCES analyzer_ast_nodes(id) ON DELETE SET NULL,
    datasource      TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    ai_description  TEXT DEFAULT '',
    is_etl          BOOLEAN DEFAULT FALSE,
    etl_operation   TEXT DEFAULT '',
    stereotype      TEXT DEFAULT '',
    embedding       vector(1536),
    extra_props     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ast_nodes_type ON analyzer_ast_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_name ON analyzer_ast_nodes(name);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_file ON analyzer_ast_nodes(file_name);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_parent ON analyzer_ast_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_embedding_hnsw
    ON analyzer_ast_nodes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 8) AST 엣지 (replaces CONTAINS, PARENT_OF, NEXT, CALL, DECLARES, FROM, WRITES, etc.)
CREATE TABLE IF NOT EXISTS analyzer_ast_edges (
    id              SERIAL PRIMARY KEY,
    from_node_id    INT NOT NULL REFERENCES analyzer_ast_nodes(id) ON DELETE CASCADE,
    to_node_id      INT NOT NULL REFERENCES analyzer_ast_nodes(id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL,
    extra_props     JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ast_edges_from ON analyzer_ast_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_ast_edges_to ON analyzer_ast_edges(to_node_id);
CREATE INDEX IF NOT EXISTS idx_ast_edges_type ON analyzer_ast_edges(edge_type);

-- 9) AST 노드 → 테이블 참조 (replaces FROM/WRITES relationships to Analyzer_Table)
CREATE TABLE IF NOT EXISTS analyzer_ast_table_refs (
    id              SERIAL PRIMARY KEY,
    ast_node_id     INT NOT NULL REFERENCES analyzer_ast_nodes(id) ON DELETE CASCADE,
    table_id        INT NOT NULL REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    ref_type        TEXT NOT NULL DEFAULT 'FROM',
    UNIQUE(ast_node_id, table_id, ref_type)
);

CREATE INDEX IF NOT EXISTS idx_ast_table_refs_ast ON analyzer_ast_table_refs(ast_node_id);
CREATE INDEX IF NOT EXISTS idx_ast_table_refs_table ON analyzer_ast_table_refs(table_id);

-- 10) User Story / Acceptance Criteria (replaces :Analyzer_UserStory, :Analyzer_AcceptanceCriteria)
CREATE TABLE IF NOT EXISTS analyzer_user_stories (
    id              SERIAL PRIMARY KEY,
    ast_node_id     INT REFERENCES analyzer_ast_nodes(id) ON DELETE CASCADE,
    title           TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    acceptance_criteria TEXT DEFAULT '',
    extra_props     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_us_ast ON analyzer_user_stories(ast_node_id);

-- 11) ETL / 리니지 (replaces :Analyzer_ETLProcess + DATA_FLOW_TO + TRANSFORMS_TO)
CREATE TABLE IF NOT EXISTS analyzer_lineage_nodes (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    node_type       TEXT NOT NULL DEFAULT 'DataSource',
    source_type     TEXT DEFAULT '',
    extra_props     JSONB DEFAULT '{}',
    UNIQUE(name, node_type)
);

CREATE TABLE IF NOT EXISTS analyzer_lineage_edges (
    id              SERIAL PRIMARY KEY,
    from_node_id    INT NOT NULL REFERENCES analyzer_lineage_nodes(id) ON DELETE CASCADE,
    to_node_id      INT NOT NULL REFERENCES analyzer_lineage_nodes(id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL DEFAULT 'DATA_FLOW_TO',
    extra_props     JSONB DEFAULT '{}',
    UNIQUE(from_node_id, to_node_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_from ON analyzer_lineage_edges(from_node_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_to ON analyzer_lineage_edges(to_node_id);

-- 12) ETL 프로시저 → 테이블 참조 (replaces ETL_READS / ETL_WRITES)
CREATE TABLE IF NOT EXISTS analyzer_etl_table_refs (
    id              SERIAL PRIMARY KEY,
    ast_node_id     INT NOT NULL REFERENCES analyzer_ast_nodes(id) ON DELETE CASCADE,
    table_id        INT NOT NULL REFERENCES analyzer_tables(id) ON DELETE CASCADE,
    ref_type        TEXT NOT NULL DEFAULT 'ETL_READS',
    UNIQUE(ast_node_id, table_id, ref_type)
);

-- 13) 용어집 (replaces :Glossary nodes)
CREATE TABLE IF NOT EXISTS analyzer_glossaries (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    type            TEXT DEFAULT 'Business',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 14) 용어 (replaces :Term nodes + :HAS_TERM relationship)
CREATE TABLE IF NOT EXISTS analyzer_terms (
    id              SERIAL PRIMARY KEY,
    glossary_id     INT NOT NULL REFERENCES analyzer_glossaries(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    status          TEXT DEFAULT 'Draft',
    synonyms        TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_terms_glossary ON analyzer_terms(glossary_id);
CREATE INDEX IF NOT EXISTS idx_terms_name ON analyzer_terms(name);

-- 15) 도메인 (replaces :Domain nodes)
CREATE TABLE IF NOT EXISTS analyzer_domains (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT DEFAULT ''
);

-- 16) 소유자 (replaces :Owner nodes)
CREATE TABLE IF NOT EXISTS analyzer_owners (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    email           TEXT DEFAULT '',
    role            TEXT DEFAULT 'Owner'
);

-- 17) 태그 (replaces :Tag nodes)
CREATE TABLE IF NOT EXISTS analyzer_tags (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    color           TEXT DEFAULT '#3498db'
);

-- 18) 용어-도메인 M:N (replaces :BELONGS_TO_DOMAIN)
CREATE TABLE IF NOT EXISTS analyzer_term_domains (
    term_id         INT NOT NULL REFERENCES analyzer_terms(id) ON DELETE CASCADE,
    domain_id       INT NOT NULL REFERENCES analyzer_domains(id) ON DELETE CASCADE,
    PRIMARY KEY (term_id, domain_id)
);

-- 19) 용어-태그 M:N (replaces :HAS_TAG)
CREATE TABLE IF NOT EXISTS analyzer_term_tags (
    term_id         INT NOT NULL REFERENCES analyzer_terms(id) ON DELETE CASCADE,
    tag_id          INT NOT NULL REFERENCES analyzer_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (term_id, tag_id)
);

-- 20) 용어-소유자 M:N (replaces :OWNED_BY)
CREATE TABLE IF NOT EXISTS analyzer_term_owners (
    term_id         INT NOT NULL REFERENCES analyzer_terms(id) ON DELETE CASCADE,
    owner_id        INT NOT NULL REFERENCES analyzer_owners(id) ON DELETE CASCADE,
    PRIMARY KEY (term_id, owner_id)
);

-- 21) 비즈니스 캘린더 (replaces :BusinessCalendar)
CREATE TABLE IF NOT EXISTS analyzer_business_calendars (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT DEFAULT '',
    year            INT,
    extra_props     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 22) 비영업일 (replaces :NonBusinessDay + :HAS_NON_BUSINESS_DAY)
CREATE TABLE IF NOT EXISTS analyzer_non_business_days (
    id              SERIAL PRIMARY KEY,
    calendar_id     INT NOT NULL REFERENCES analyzer_business_calendars(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    reason          TEXT DEFAULT '',
    day_type        TEXT DEFAULT 'non_business',
    UNIQUE(calendar_id, date)
);

-- 23) 공휴일 (replaces :Holiday + :HAS_HOLIDAY)
CREATE TABLE IF NOT EXISTS analyzer_holidays (
    id              SERIAL PRIMARY KEY,
    calendar_id     INT NOT NULL REFERENCES analyzer_business_calendars(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    name            TEXT NOT NULL,
    holiday_type    TEXT DEFAULT 'public',
    UNIQUE(calendar_id, date)
);
