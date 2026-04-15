"""Neo4j dump → K-AIR-GraphDB 통합 마이그레이션 스크립트

기존 migrate_neo4j_to_age.py의 온톨로지 그래프 마이그레이션에 더해,
t2s_* / analyzer_* 관계형 테이블 초기 적재를 수행하는 통합 엔트리포인트.

사용법:
    python scripts/migrate_neo4j_to_kair_graphdb.py [--graph-only] [--tables-only]
"""

import argparse
import json
import os
import sys
import asyncio
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "libs"))

NODES_FILE = os.path.join(PROJECT_ROOT, "sample", "neo4j_nodes.json")
RELS_FILE = os.path.join(PROJECT_ROOT, "sample", "neo4j_relationships.json")
SCHEMA_FILE = os.path.join(PROJECT_ROOT, "sample", "neo4j_schema_report.json")

PG_DSN = "postgresql://kair:kair_pass@localhost:15432/kair_graphdb"


def migrate_graph():
    """AGE 온톨로지 그래프 마이그레이션 (기존 migrate_neo4j_to_age.py 호출)"""
    print("=" * 60)
    print(" Phase A: Neo4j → K-AIR-GraphDB AGE 그래프 마이그레이션")
    print("=" * 60)
    from migrate_neo4j_to_age import main as age_main
    age_main()


async def migrate_tables():
    """Neo4j 덤프에서 t2s_*/analyzer_* 관계형 테이블 적재"""
    import asyncpg

    print("\n" + "=" * 60)
    print(" Phase B: Neo4j → K-AIR-GraphDB 관계형 테이블 적재")
    print("=" * 60)

    if not os.path.exists(NODES_FILE) or not os.path.exists(RELS_FILE):
        print("  [SKIP] Neo4j JSON 파일 없음")
        return

    with open(NODES_FILE, "r", encoding="utf-8") as f:
        nodes = json.load(f)
    with open(RELS_FILE, "r", encoding="utf-8") as f:
        rels = json.load(f)

    pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=5)

    label_groups = {}
    for n in nodes:
        for lbl in n.get("labels", []):
            label_groups.setdefault(lbl, []).append(n)

    stats = {"tables": 0, "columns": 0, "fks": 0, "schemas": 0, "queries": 0}

    async with pool.acquire() as conn:
        # T2S Tables
        t2s_nodes = label_groups.get("Fabric_Table", []) + label_groups.get("Table", [])
        print(f"\n  [B1] t2s_tables: {len(t2s_nodes)} 건 적재 중...")
        for n in t2s_nodes:
            props = n.get("properties", {})
            try:
                await conn.execute(
                    """INSERT INTO t2s_tables (db, schema_name, name, description)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (db, schema_name, name) DO NOTHING""",
                    props.get("db", ""),
                    props.get("schema", "public"),
                    props.get("name", ""),
                    props.get("description", ""),
                )
                stats["tables"] += 1
            except Exception:
                pass
        print(f"    → {stats['tables']} 건 INSERT/SKIP")

        # T2S Columns
        t2s_col_nodes = label_groups.get("Fabric_Column", []) + label_groups.get("Column", [])
        print(f"\n  [B2] t2s_columns: {len(t2s_col_nodes)} 건 적재 중...")
        for n in t2s_col_nodes:
            props = n.get("properties", {})
            fqn = props.get("fqn", "")
            if not fqn:
                continue
            table_name = props.get("table_name", "")
            table_id = await conn.fetchval(
                "SELECT id FROM t2s_tables WHERE name = $1 LIMIT 1", table_name
            )
            if not table_id:
                continue
            try:
                await conn.execute(
                    """INSERT INTO t2s_columns (table_id, fqn, name, dtype, description)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (fqn) DO NOTHING""",
                    table_id,
                    fqn,
                    props.get("name", ""),
                    props.get("type", ""),
                    props.get("description", ""),
                )
                stats["columns"] += 1
            except Exception:
                pass
        print(f"    → {stats['columns']} 건 INSERT/SKIP")

        # Analyzer Tables
        analyzer_nodes = label_groups.get("Analyzer_Table", [])
        print(f"\n  [B3] analyzer_tables: {len(analyzer_nodes)} 건 적재 중...")
        a_stats = 0
        for n in analyzer_nodes:
            props = n.get("properties", {})
            try:
                await conn.execute(
                    """INSERT INTO analyzer_tables (db, schema_name, name, description)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (db, schema_name, name) DO NOTHING""",
                    props.get("db", ""),
                    props.get("schema", "public"),
                    props.get("name", ""),
                    props.get("description", ""),
                )
                a_stats += 1
            except Exception:
                pass
        print(f"    → {a_stats} 건 INSERT/SKIP")

        # Analyzer Columns
        analyzer_cols = label_groups.get("Analyzer_Column", [])
        print(f"\n  [B4] analyzer_columns: {len(analyzer_cols)} 건 적재 중...")
        ac_stats = 0
        for n in analyzer_cols:
            props = n.get("properties", {})
            fqn = props.get("fqn", "")
            if not fqn:
                continue
            try:
                await conn.execute(
                    """INSERT INTO analyzer_columns (fqn, name, dtype, description)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (fqn) DO NOTHING""",
                    fqn,
                    props.get("name", ""),
                    props.get("type", ""),
                    props.get("description", ""),
                )
                ac_stats += 1
            except Exception:
                pass
        print(f"    → {ac_stats} 건 INSERT/SKIP")

    await pool.close()

    print(f"\n  [Summary]")
    print(f"    t2s_tables:      {stats['tables']}")
    print(f"    t2s_columns:     {stats['columns']}")
    print(f"    analyzer_tables: {a_stats}")
    print(f"    analyzer_cols:   {ac_stats}")


def main():
    parser = argparse.ArgumentParser(description="Neo4j → K-AIR-GraphDB 통합 마이그레이션")
    parser.add_argument("--graph-only", action="store_true", help="AGE 그래프만 마이그레이션")
    parser.add_argument("--tables-only", action="store_true", help="관계형 테이블만 적재")
    args = parser.parse_args()

    if args.graph_only:
        migrate_graph()
    elif args.tables_only:
        asyncio.run(migrate_tables())
    else:
        migrate_graph()
        asyncio.run(migrate_tables())

    print("\n=== K-AIR-GraphDB 마이그레이션 완료 ===")


if __name__ == "__main__":
    main()
