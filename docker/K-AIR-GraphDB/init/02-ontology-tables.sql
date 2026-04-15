-- ============================================================
-- P1-02: ontology_schemas RDB 메타 테이블
-- AGE 그래프와 병행하여 스키마 메타데이터를 RDB에 저장.
-- domain-layer가 스키마 목록·버전·JSON 전문을 빠르게 조회할 때 사용.
-- ============================================================

CREATE TABLE IF NOT EXISTS ontology_schemas (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    domain      TEXT,
    version     INTEGER DEFAULT 1,
    schema_json JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ontology_schemas_domain
    ON ontology_schemas (domain);
CREATE INDEX IF NOT EXISTS idx_ontology_schemas_name
    ON ontology_schemas USING gin (to_tsvector('simple', name));

COMMENT ON TABLE ontology_schemas IS
    'AGE ontology_graph와 병행 — 스키마 메타+JSON 전문 저장 (domain-layer 빠른 조회용)';

-- ============================================================
-- P1-02: ontology_schema_versions (버전 이력)
-- ============================================================

CREATE TABLE IF NOT EXISTS ontology_schema_versions (
    id          SERIAL PRIMARY KEY,
    schema_id   TEXT NOT NULL REFERENCES ontology_schemas(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    schema_json JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (schema_id, version)
);

COMMENT ON TABLE ontology_schema_versions IS
    '온톨로지 스키마 버전별 스냅샷 이력';
