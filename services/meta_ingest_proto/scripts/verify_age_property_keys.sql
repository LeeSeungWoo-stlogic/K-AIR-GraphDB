-- AGE: 물리 계약 정점의 속성 키 목록(keys)
-- 선행: LOAD 'age'; SET search_path = ag_catalog, "$user", public;
-- datasource / fqn 접두는 META_DB_LABEL verify_5tables_rwis 기준

LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- (1) Table 5개: 계약 필드 + AGE keys() 배열
SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)
  WHERE t._meta_ingest = true AND t.datasource = 'verify_5tables_rwis'
  RETURN t.name AS table_name,
         t.schema AS schema_name,
         t.table_type AS table_type,
         t.db_exists AS db_exists,
         t.datasource AS datasource,
         t._meta_ingest AS meta_ingest,
         left(coalesce(t.description,''), 60) AS description_60,
         left(coalesce(t.analyzed_description,''), 40) AS analyzed_40,
         t._physical_vertex_id AS physical_vertex_id,
         keys(t) AS property_keys
  ORDER BY t.name
  LIMIT 5
$$) AS (
  table_name agtype, schema_name agtype, table_type agtype, db_exists agtype,
  datasource agtype, meta_ingest agtype, description_60 agtype, analyzed_40 agtype,
  physical_vertex_id agtype, property_keys agtype
);

-- (2) 두 테이블(dept, emp) 소속 Column: keys(c)
SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)-[:HAS_COLUMN]->(c:Column)
  WHERE t._meta_ingest = true
    AND t.datasource = 'verify_5tables_rwis'
    AND (t.name = 'dept' OR t.name = 'emp')
  RETURN t.name AS table_name,
         c.name AS column_name,
         c.ordinal_position AS ord,
         c.fqn AS fqn,
         keys(c) AS property_keys
  ORDER BY t.name, c.name
$$) AS (
  table_name agtype, column_name agtype, ord agtype, fqn agtype, property_keys agtype
);
