-- meta_ingest E2E 검증용 RWIS 스키마 — 테이블 5개 + 복수 FK
-- 적용: 원천 Postgres (예: 검증용 컨테이너 55432, DB 이름은 환경에 맞게)
-- META_DB_LABEL 권장: verify_5tables_rwis

CREATE SCHEMA IF NOT EXISTS "RWIS";

CREATE TABLE IF NOT EXISTS "RWIS".region (
    id int PRIMARY KEY,
    name varchar(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS "RWIS".site (
    id int PRIMARY KEY,
    region_id int NOT NULL,
    code varchar(50),
    CONSTRAINT fk_site_region FOREIGN KEY (region_id) REFERENCES "RWIS".region (id)
);

CREATE TABLE IF NOT EXISTS "RWIS".dept (
    id int PRIMARY KEY,
    name varchar(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS "RWIS".emp (
    id int PRIMARY KEY,
    dept_id int NOT NULL,
    emp_name varchar(100) NOT NULL,
    CONSTRAINT fk_emp_dept FOREIGN KEY (dept_id) REFERENCES "RWIS".dept (id)
);

CREATE TABLE IF NOT EXISTS "RWIS".asset (
    id int PRIMARY KEY,
    site_id int NOT NULL,
    tag varchar(50),
    CONSTRAINT fk_asset_site FOREIGN KEY (site_id) REFERENCES "RWIS".site (id)
);

COMMENT ON TABLE "RWIS".region IS 'region master';
COMMENT ON TABLE "RWIS".dept IS 'dept master';
COMMENT ON COLUMN "RWIS".emp.emp_name IS 'employee display name';

INSERT INTO "RWIS".region (id, name) VALUES (1, 'metro') ON CONFLICT DO NOTHING;
INSERT INTO "RWIS".site (id, region_id, code) VALUES (1, 1, 'S01') ON CONFLICT DO NOTHING;
INSERT INTO "RWIS".dept (id, name) VALUES (1, 'dev') ON CONFLICT DO NOTHING;
INSERT INTO "RWIS".emp (id, dept_id, emp_name) VALUES (1, 1, 'alice') ON CONFLICT DO NOTHING;
INSERT INTO "RWIS".asset (id, site_id, tag) VALUES (1, 1, 'PUMP-01') ON CONFLICT DO NOTHING;
