-- meta_ingest E2E 검증용 최소 스키마 (스키마명 RWIS)
CREATE SCHEMA IF NOT EXISTS "RWIS";

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

COMMENT ON TABLE "RWIS".dept IS '부서';
COMMENT ON COLUMN "RWIS".emp.emp_name IS '직원명';

INSERT INTO "RWIS".dept (id, name) VALUES (1, '개발') ON CONFLICT DO NOTHING;
INSERT INTO "RWIS".emp (id, dept_id, emp_name) VALUES (1, 1, '홍길동') ON CONFLICT DO NOTHING;
