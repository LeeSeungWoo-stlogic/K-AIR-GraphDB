from __future__ import annotations

from typing import Any

import psycopg

from age_graph_repository.physical_meta import build_physical_meta_refresh

from ..config import TargetConfig, age_graph_name, dsn_pg


def age_prepare_session(cur: psycopg.Cursor) -> None:
    cur.execute("LOAD 'age'")
    cur.execute('SET search_path = ag_catalog, "$user", public')


def age_run_cypher(cur: psycopg.Cursor, graph: str, cypher: str) -> None:
    cur.execute(f"SELECT * FROM cypher('{graph}', $${cypher}$$) AS (x agtype);")


def apply_catalog_to_age_physical(tgt: TargetConfig, catalog: dict[str, Any]) -> dict[str, int]:
    graph = age_graph_name()
    statements, summary = build_physical_meta_refresh(catalog)
    with psycopg.connect(dsn_pg(tgt, tgt.dbname)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            age_prepare_session(cur)
            for stmt in statements:
                age_run_cypher(cur, graph, stmt)
            age_prepare_session(cur)
    return summary
