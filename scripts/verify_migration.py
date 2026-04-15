"""
Migration verification script.
Compares Neo4j (source) vs AGE (target) across multiple dimensions:
  1. Total node/relationship counts
  2. Per-label node counts
  3. Per-type relationship counts
  4. Path traversal (ontology chain)
  5. Property integrity (sample-based)
"""
import json
import os
import sys
import psycopg2
from neo4j import GraphDatabase

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

NEO4J_URI = "bolt://localhost:17687"
NEO4J_AUTH = ("neo4j", "password123")
PG_CONN = {
    "host": "localhost", "port": 15432,
    "dbname": "kair_graphdb", "user": "kair", "password": "kair_pass",
}
GRAPH_NAME = "ontology_graph"

results = []


def log(category, test_name, neo4j_val, age_val, match):
    status = "PASS" if match else "FAIL"
    results.append({
        "category": category, "test": test_name,
        "neo4j": neo4j_val, "age": age_val, "status": status
    })
    icon = "OK" if match else "!!"
    print(f"  [{icon}] {test_name}: Neo4j={neo4j_val}  AGE={age_val}", flush=True)


def age_query(cur, cypher):
    sql = f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$ {cypher} $$) AS (r agtype);"
    cur.execute(sql)
    return cur.fetchall()


def verify_total_counts(neo_session, age_cur):
    print("\n[1/5] Total Counts", flush=True)
    neo_nodes = neo_session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    age_rows = age_query(age_cur, "MATCH (n) RETURN count(n)")
    age_nodes = int(str(age_rows[0][0]).strip('"'))
    log("counts", "total_nodes", neo_nodes, age_nodes, neo_nodes == age_nodes)

    neo_rels = neo_session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    age_rows = age_query(age_cur, "MATCH ()-[r]->() RETURN count(r)")
    age_rels = int(str(age_rows[0][0]).strip('"'))
    log("counts", "total_relationships", neo_rels, age_rels, neo_rels == age_rels)


def verify_label_counts(neo_session, age_cur):
    print("\n[2/5] Per-Label Node Counts", flush=True)

    # For single-label nodes (most specific label == only label), direct match
    # For multi-label nodes, AGE stores only the most specific label;
    # others are in _labels property. We verify via _labels JSON search.
    neo_label_combos = neo_session.run(
        "MATCH (n) RETURN labels(n) AS lbls, count(*) AS cnt ORDER BY cnt DESC LIMIT 30"
    )
    combo_list = [{"labels": r["lbls"], "count": r["cnt"]} for r in neo_label_combos]

    # Verify top single-label groups (where MATCH (n:Label) should directly match)
    print("  -- Single-label groups (direct match expected) --", flush=True)
    single_labels = [c for c in combo_list if len(c["labels"]) == 1][:10]
    for combo in single_labels:
        label = combo["labels"][0]
        neo_cnt = combo["count"]
        try:
            age_rows = age_query(age_cur, f"MATCH (n:{label}) RETURN count(n)")
            age_cnt = int(str(age_rows[0][0]).strip('"'))
        except Exception:
            age_cnt = "ERROR"
        match = neo_cnt == age_cnt if isinstance(age_cnt, int) else False
        log("labels_single", f"label:{label} (single)", neo_cnt, age_cnt, match)

    # Verify total for most-specific labels (last label in combo)
    print("  -- Multi-label groups (most-specific label in AGE) --", flush=True)
    multi_labels = [c for c in combo_list if len(c["labels"]) > 1][:10]
    for combo in multi_labels:
        primary = combo["labels"][-1]
        neo_cnt = combo["count"]
        try:
            age_rows = age_query(age_cur, f"MATCH (n:{primary}) RETURN count(n)")
            age_cnt = int(str(age_rows[0][0]).strip('"'))
        except Exception:
            age_cnt = "ERROR"
        # AGE count for primary label may include nodes from OTHER combos with same last label
        # so we just check that age_cnt >= neo_cnt
        match = isinstance(age_cnt, int) and age_cnt >= neo_cnt
        log("labels_multi", f"label:{primary} (primary, combo={combo['labels']})",
            neo_cnt, age_cnt, match)

    return 0


def verify_rel_type_counts(neo_session, age_cur):
    print("\n[3/5] Per-Type Relationship Counts (top 15)", flush=True)
    neo_result = neo_session.run(
        "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY c DESC LIMIT 15"
    )
    neo_types = {r["t"]: r["c"] for r in neo_result}

    mismatches = 0
    for rtype, neo_cnt in neo_types.items():
        try:
            age_rows = age_query(age_cur, f"MATCH ()-[r:{rtype}]->() RETURN count(r)")
            age_cnt = int(str(age_rows[0][0]).strip('"'))
        except Exception:
            age_cnt = "ERROR"

        match = neo_cnt == age_cnt if isinstance(age_cnt, int) else False
        if not match:
            mismatches += 1
        log("rel_types", f"rel:{rtype}", neo_cnt, age_cnt, match)

    return mismatches


def verify_path_traversal(neo_session, age_cur):
    print("\n[4/5] Path Traversal (Ontology Chains)", flush=True)

    path_tests = [
        ("SUBCLASS_OF depth 1", "MATCH (a)-[:SUBCLASS_OF]->(b) RETURN count(*)"),
        ("SUBCLASS_OF depth 2", "MATCH (a)-[:SUBCLASS_OF]->()-[:SUBCLASS_OF]->(b) RETURN count(*)"),
        ("PART_OF depth 1", "MATCH (a)-[:PART_OF]->(b) RETURN count(*)"),
        ("INSTANCE_OF depth 1", "MATCH (a)-[:INSTANCE_OF]->(b) RETURN count(*)"),
        ("FLOWS_INTO depth 1", "MATCH (a)-[:FLOWS_INTO]->(b) RETURN count(*)"),
        ("NEXT_PROCESS depth 1", "MATCH (a)-[:NEXT_PROCESS]->(b) RETURN count(*)"),
    ]

    for test_name, cypher in path_tests:
        neo_res = neo_session.run(cypher.replace("count(*)", "count(*) AS c")).single()["c"]
        try:
            age_rows = age_query(age_cur, cypher)
            age_res = int(str(age_rows[0][0]).strip('"'))
        except Exception as e:
            age_res = f"ERROR: {str(e)[:80]}"
        match = neo_res == age_res if isinstance(age_res, int) else False
        log("paths", test_name, neo_res, age_res, match)


def verify_property_integrity(neo_session, age_cur):
    print("\n[5/5] Property Integrity (Sample Checks)", flush=True)

    # Check KPI node count match
    neo_kpi_cnt = neo_session.run("MATCH (k:KPI) RETURN count(k) AS c").single()["c"]
    try:
        age_rows = age_query(age_cur, "MATCH (k:KPI) RETURN count(k)")
        age_kpi_cnt = int(str(age_rows[0][0]).strip('"'))
    except Exception:
        age_kpi_cnt = "ERROR"
    log("properties", "KPI node count", neo_kpi_cnt, age_kpi_cnt,
        neo_kpi_cnt == age_kpi_cnt if isinstance(age_kpi_cnt, int) else False)

    # Check KPI property via _neo4j_id
    neo_kpis = neo_session.run(
        "MATCH (k:KPI) RETURN id(k) AS nid, k.name AS name, k.id AS kid ORDER BY k.id LIMIT 5"
    )
    neo_kpi_list = [{"nid": r["nid"], "name": r["name"], "kid": r["kid"]} for r in neo_kpis]

    for kpi in neo_kpi_list:
        nid = kpi["nid"]
        try:
            age_rows = age_query(
                age_cur,
                f"MATCH (k:KPI) WHERE k._neo4j_id = {nid} RETURN k.name, k.id"
            )
            if age_rows:
                age_name = str(age_rows[0][0]).strip('"')
                match = str(kpi["name"]) == age_name
            else:
                age_name = "NOT FOUND"
                match = False
        except Exception as e:
            age_name = f"ERROR: {str(e)[:80]}"
            match = False
        log("properties", f"KPI[neo4j_id={nid}] name match", kpi["name"], age_name, match)

    # Check Process count
    neo_proc_cnt = neo_session.run("MATCH (p:Process) RETURN count(p) AS c").single()["c"]
    try:
        age_rows = age_query(age_cur, "MATCH (p:Process) RETURN count(p)")
        age_proc_cnt = int(str(age_rows[0][0]).strip('"'))
    except Exception:
        age_proc_cnt = "ERROR"
    log("properties", "Process node count", neo_proc_cnt, age_proc_cnt,
        neo_proc_cnt == age_proc_cnt if isinstance(age_proc_cnt, int) else False)

    # Check sample nodes via _neo4j_id for data integrity
    neo_sample = neo_session.run(
        "MATCH (n) WHERE n.name IS NOT NULL RETURN id(n) AS nid, labels(n) AS lbls, n.name AS name "
        "ORDER BY id(n) LIMIT 10"
    )
    for r in neo_sample:
        nid = r["nid"]
        neo_name = r["name"]
        primary_label = r["lbls"][-1] if r["lbls"] else "UnknownNode"
        try:
            age_rows = age_query(
                age_cur,
                f"MATCH (n:{primary_label}) WHERE n._neo4j_id = {nid} RETURN n.name"
            )
            if age_rows:
                age_name = str(age_rows[0][0]).strip('"')
                match = str(neo_name) == age_name
            else:
                age_name = "NOT FOUND"
                match = False
        except Exception as e:
            age_name = f"ERROR: {str(e)[:80]}"
            match = False
        log("properties", f"Node[{nid}:{primary_label}].name", neo_name, age_name, match)


def main():
    print("=" * 60, flush=True)
    print("  Neo4j vs AGE Migration Verification", flush=True)
    print("=" * 60, flush=True)

    neo_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    neo_driver.verify_connectivity()

    pg_conn = psycopg2.connect(**PG_CONN)
    pg_conn.autocommit = True
    age_cur = pg_conn.cursor()
    age_cur.execute("LOAD 'age';")
    age_cur.execute("SET search_path = ag_catalog, public;")

    with neo_driver.session() as neo_session:
        verify_total_counts(neo_session, age_cur)
        verify_label_counts(neo_session, age_cur)
        verify_rel_type_counts(neo_session, age_cur)
        verify_path_traversal(neo_session, age_cur)
        verify_property_integrity(neo_session, age_cur)

    age_cur.close()
    pg_conn.close()
    neo_driver.close()

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    print("\n" + "=" * 60, flush=True)
    print(f"  RESULTS: {passed}/{total} PASSED, {failed} FAILED", flush=True)
    print("=" * 60, flush=True)

    if failed > 0:
        print("\nFailed tests:", flush=True)
        for r in results:
            if r["status"] == "FAIL":
                print(f"  - [{r['category']}] {r['test']}: neo4j={r['neo4j']}, age={r['age']}", flush=True)

    report_path = os.path.join(PROJECT_ROOT, "sample", "verification_results.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {"passed": passed, "failed": failed, "total": total},
            "details": results
        }, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results: {report_path}", flush=True)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
