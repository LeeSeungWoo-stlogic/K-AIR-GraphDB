LOAD 'age';
SET search_path = ag_catalog, "$user", public;

SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)
  WHERE t._meta_ingest = true AND t.datasource = 'rwis_robo_postgres'
  RETURN t.name, t.schema, t.db_exists, t.datasource, keys(t) AS k
  ORDER BY t.name LIMIT 1
$$) AS (name agtype, schema agtype, db_exists agtype, datasource agtype, k agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH (c:Column)
  WHERE c._meta_ingest = true AND c.fqn STARTS WITH 'rwis_robo_postgres.RWIS'
  RETURN c.name, c.ordinal_position, c.is_unique, c.is_primary_key
  ORDER BY c.fqn LIMIT 1
$$) AS (cname agtype, ord agtype, isu agtype, pk agtype);

SELECT * FROM cypher('ontology_graph', $$
  MATCH ()-[r:FK_TO]->()
  RETURN r.constraint, r.position LIMIT 1
$$) AS (cons agtype, pos agtype);
