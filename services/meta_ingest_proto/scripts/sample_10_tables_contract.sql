LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- 10 tables: every Table contract field + keys() array (must match 9 contract body + ops keys)
SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)
  WHERE t._meta_ingest = true AND t.datasource = 'rwis_robo_postgres'
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
  LIMIT 10
$$) AS (
  table_name agtype, schema_name agtype, table_type agtype, db_exists agtype,
  datasource agtype, meta_ingest agtype, description_60 agtype, analyzed_40 agtype,
  physical_vertex_id agtype, property_keys agtype
);
