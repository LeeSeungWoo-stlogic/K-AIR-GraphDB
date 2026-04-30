LOAD 'age';
SET search_path = ag_catalog, "$user", public;

SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)
  WHERE t._meta_ingest = true AND t.datasource = 'verify_min_rwis'
  RETURN t.name, t.schema, t.datasource, t.db_exists
  ORDER BY t.name
$$) AS (name agtype, schema agtype, datasource agtype, db_exists agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH (c:Column)
  WHERE c._meta_ingest = true AND c.fqn STARTS WITH 'verify_min_rwis.RWIS'
  RETURN c.name, c.ordinal_position, c.is_primary_key, c.fqn
  ORDER BY c.fqn
$$) AS (cname agtype, ord agtype, pk agtype, fqn agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH (a:Column)-[r:FK_TO]->(b:Column)
  WHERE a.fqn STARTS WITH 'verify_min_rwis'
  RETURN a.name AS from_col, b.name AS to_col, r.constraint, r.position
$$) AS (from_col agtype, to_col agtype, cons agtype, pos agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)-[h:HAS_COLUMN]->(c:Column)
  WHERE t._meta_ingest = true AND t.datasource = 'verify_min_rwis'
  RETURN count(h)
$$) AS (cnt agtype);
