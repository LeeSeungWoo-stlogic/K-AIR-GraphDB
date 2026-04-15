"""
Neo4j dump -> JSON export script.
Exports all nodes and relationships from Neo4j to JSON files for AGE migration.
"""
import json
import sys
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:17687"
NEO4J_AUTH = ("neo4j", "password123")
OUTPUT_DIR = "sample"


def export_nodes(driver):
    nodes = []
    with driver.session() as session:
        result = session.run(
            "MATCH (n) RETURN id(n) AS neo4j_id, labels(n) AS labels, properties(n) AS props"
        )
        for record in result:
            nodes.append({
                "neo4j_id": record["neo4j_id"],
                "labels": record["labels"],
                "properties": dict(record["props"]),
            })
    return nodes


def export_relationships(driver):
    rels = []
    with driver.session() as session:
        result = session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN id(r) AS rel_id, type(r) AS rel_type, "
            "id(a) AS start_id, id(b) AS end_id, properties(r) AS props"
        )
        for record in result:
            rels.append({
                "rel_id": record["rel_id"],
                "rel_type": record["rel_type"],
                "start_id": record["start_id"],
                "end_id": record["end_id"],
                "properties": dict(record["props"]),
            })
    return rels


def export_schema_report(driver):
    report = {}
    with driver.session() as session:
        labels = session.run("CALL db.labels() YIELD label RETURN collect(label) AS labels")
        report["labels"] = labels.single()["labels"]

        rel_types = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN collect(relationshipType) AS types")
        report["relationship_types"] = rel_types.single()["types"]

        node_counts = session.run(
            "MATCH (n) RETURN labels(n) AS labels, count(*) AS cnt ORDER BY cnt DESC"
        )
        report["node_counts"] = [
            {"labels": r["labels"], "count": r["cnt"]} for r in node_counts
        ]

        rel_counts = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS cnt ORDER BY cnt DESC"
        )
        report["relationship_counts"] = [
            {"type": r["type"], "count": r["cnt"]} for r in rel_counts
        ]

        totals = session.run(
            "MATCH (n) WITH count(n) AS nodes "
            "OPTIONAL MATCH ()-[r]->() "
            "RETURN nodes, count(r) AS rels"
        )
        t = totals.single()
        report["total_nodes"] = t["nodes"]
        report["total_relationships"] = t["rels"]

    return report


class NeoEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
            return list(obj)
        return super().default(obj)


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        driver.verify_connectivity()
        print("[1/3] Exporting schema report...")
        report = export_schema_report(driver)
        with open(f"{OUTPUT_DIR}/neo4j_schema_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, cls=NeoEncoder)
        print(f"  -> {report['total_nodes']} nodes, {report['total_relationships']} relationships")
        print(f"  -> {len(report['labels'])} labels, {len(report['relationship_types'])} relationship types")

        print("[2/3] Exporting nodes...")
        nodes = export_nodes(driver)
        with open(f"{OUTPUT_DIR}/neo4j_nodes.json", "w", encoding="utf-8") as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2, cls=NeoEncoder)
        print(f"  -> {len(nodes)} nodes exported")

        print("[3/3] Exporting relationships...")
        rels = export_relationships(driver)
        with open(f"{OUTPUT_DIR}/neo4j_relationships.json", "w", encoding="utf-8") as f:
            json.dump(rels, f, ensure_ascii=False, indent=2, cls=NeoEncoder)
        print(f"  -> {len(rels)} relationships exported")

        print("\nExport complete!")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
