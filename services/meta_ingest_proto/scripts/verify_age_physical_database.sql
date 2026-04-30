-- 물리 인제스트 후 :Database / HAS_TABLE 샘플 확인 (META_DB_LABEL 환경에 맞게 datasource 필터 조정)
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

SELECT * FROM cypher('ontology_graph', $$
  MATCH (d:Database)
  WHERE d._meta_ingest = true
  RETURN d.meta_db_label, d.source_engine, d._physical_vertex_id
  LIMIT 5
$$) AS (meta_db_label agtype, source_engine agtype, vid agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH (d:Database)-[r:HAS_TABLE]->(t:Table)
  WHERE d._meta_ingest = true AND t._meta_ingest = true
  RETURN count(r)
$$) AS (has_table_cnt agtype);
