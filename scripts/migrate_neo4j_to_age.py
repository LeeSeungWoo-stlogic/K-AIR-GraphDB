"""
Neo4j -> Apache AGE full migration (nodes + relationships).
Uses Cypher for nodes (label auto-creation) and direct SQL INSERT for relationships.
"""
import json
import os
import re
import psycopg2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

PG_CONN = {
    "host": "localhost", "port": 15432,
    "dbname": "kair_graphdb", "user": "kair", "password": "kair_pass",
}
GRAPH_NAME = "ontology_graph"
NODES_FILE = os.path.join(PROJECT_ROOT, "sample", "neo4j_nodes.json")
RELS_FILE = os.path.join(PROJECT_ROOT, "sample", "neo4j_relationships.json")


def sanitize_label(label: str) -> str:
    label = re.sub(r"[^a-zA-Z0-9_]", "_", label)
    if label and label[0].isdigit():
        label = "_" + label
    return label


def pick_primary_label(labels: list) -> str:
    if not labels:
        return "UnknownNode"
    return sanitize_label(labels[-1])


def escape_val(val):
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        if isinstance(val, float) and (val != val):
            return "null"
        return str(val)
    if isinstance(val, list):
        inner = ", ".join(escape_val(v) for v in val)
        return f"[{inner}]"
    s = str(val).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def build_props(props: dict, extra: dict = None) -> str:
    all_p = {}
    if props:
        all_p.update(props)
    if extra:
        all_p.update(extra)
    if not all_p:
        return ""
    parts = []
    for k, v in all_p.items():
        safe_k = re.sub(r"[^a-zA-Z0-9_]", "_", k)
        if safe_k and safe_k[0].isdigit():
            safe_k = "_" + safe_k
        parts.append(f"{safe_k}: {escape_val(v)}")
    return "{" + ", ".join(parts) + "}"


def exec_cypher(cur, cypher: str):
    sql = f"SELECT * FROM ag_catalog.cypher('{GRAPH_NAME}', $$ {cypher} $$) AS (r agtype);"
    cur.execute(sql)
    return cur.fetchone()


def main():
    print("=== Neo4j -> AGE Full Migration ===", flush=True)

    print("[1/6] Loading JSON...", flush=True)
    with open(NODES_FILE, "r", encoding="utf-8") as f:
        nodes = json.load(f)
    with open(RELS_FILE, "r", encoding="utf-8") as f:
        rels = json.load(f)
    print(f"  {len(nodes)} nodes, {len(rels)} relationships", flush=True)

    print("[2/6] Connecting...", flush=True)
    conn = psycopg2.connect(**PG_CONN)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("LOAD 'age';")
    cur.execute("SET search_path = ag_catalog, public;")

    # Pre-create all vertex and edge labels
    all_node_labels = set()
    all_edge_labels = set()
    for n in nodes:
        all_node_labels.add(pick_primary_label(n["labels"]))
    for r in rels:
        all_edge_labels.add(sanitize_label(r["rel_type"]))

    print(f"[3/6] Creating {len(all_node_labels)} vertex labels + {len(all_edge_labels)} edge labels...", flush=True)
    for lbl in all_node_labels:
        try:
            cur.execute(f"SELECT * FROM ag_catalog.create_vlabel('{GRAPH_NAME}', '{lbl}');")
        except Exception:
            conn.rollback()
            cur.execute("LOAD 'age';")
            cur.execute("SET search_path = ag_catalog, public;")

    for lbl in all_edge_labels:
        try:
            cur.execute(f"SELECT * FROM ag_catalog.create_elabel('{GRAPH_NAME}', '{lbl}');")
        except Exception:
            conn.rollback()
            cur.execute("LOAD 'age';")
            cur.execute("SET search_path = ag_catalog, public;")

    print("[4/6] Migrating nodes via Cypher...", flush=True)
    id_map = {}
    failed_nodes = 0
    for i, node in enumerate(nodes):
        label = pick_primary_label(node["labels"])
        extra = {"_neo4j_id": node["neo4j_id"], "_labels": json.dumps(node["labels"])}
        props_str = build_props(node["properties"], extra)

        try:
            result = exec_cypher(cur, f"CREATE (n:{label} {props_str}) RETURN id(n)")
            if result:
                age_id = str(result[0]).strip('"')
                id_map[node["neo4j_id"]] = age_id
        except Exception as e:
            failed_nodes += 1
            if failed_nodes <= 3:
                print(f"  [WARN] node {node['neo4j_id']} ({label}): {str(e)[:100]}", flush=True)
            conn.rollback()
            cur.execute("LOAD 'age';")
            cur.execute("SET search_path = ag_catalog, public;")

        if (i + 1) % 2000 == 0 or (i + 1) == len(nodes):
            print(f"  Nodes: {i+1}/{len(nodes)} (ok={len(id_map)}, fail={failed_nodes})", flush=True)

    print(f"\n[5/6] Migrating relationships via direct SQL...", flush=True)
    success = 0
    skipped = 0
    failed_rels = 0

    for i, rel in enumerate(rels):
        s_id = rel["start_id"]
        e_id = rel["end_id"]
        if s_id not in id_map or e_id not in id_map:
            skipped += 1
            if (i + 1) % 10000 == 0 or (i + 1) == len(rels):
                print(f"  Rels: {i+1}/{len(rels)} (ok={success}, skip={skipped}, fail={failed_rels})", flush=True)
            continue

        rtype = sanitize_label(rel["rel_type"])
        start_age = id_map[s_id]
        end_age = id_map[e_id]
        props = json.dumps(rel["properties"]) if rel["properties"] else "{}"

        try:
            cur.execute(
                f'INSERT INTO {GRAPH_NAME}."{rtype}" (start_id, end_id, properties) '
                f"VALUES (%s, %s, %s::agtype);",
                (start_age, end_age, props)
            )
            success += 1
        except Exception as e:
            failed_rels += 1
            if failed_rels <= 3:
                print(f"  [WARN] {rtype}: {str(e)[:100]}", flush=True)
            conn.rollback()
            cur.execute("LOAD 'age';")
            cur.execute("SET search_path = ag_catalog, public;")

        if (i + 1) % 10000 == 0 or (i + 1) == len(rels):
            print(f"  Rels: {i+1}/{len(rels)} (ok={success}, skip={skipped}, fail={failed_rels})", flush=True)

    cur.close()
    conn.close()

    print(f"\n[6/6] Summary", flush=True)
    print(f"  Nodes:         {len(id_map)}/{len(nodes)} (fail={failed_nodes})", flush=True)
    print(f"  Relationships: {success}/{len(rels)} (skip={skipped}, fail={failed_rels})", flush=True)
    print("=== Migration Complete ===", flush=True)


if __name__ == "__main__":
    main()
