"""
FK/관계 유틸리티 — neo4j_utils.py drop-in 대체.

Neo4j Cypher MATCH 패턴을 SQL JOIN으로 전환한다.
함수 시그니처는 원본과 동일하게 유지하되,
neo4j_session: AsyncSession → pg_conn: PgConnection 으로 교체.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .pg_connection import PgConnection

RELATIONSHIP_RANKS = {
    "HAS_COLUMN → FK_TO → HAS_COLUMN": 100,
}
DEFAULT_RELATIONSHIP_SCORE = 1

RELATIONSHIP_TYPE_MAP = {
    "HAS_COLUMN → FK_TO → HAS_COLUMN": "외래키 관계",
}


async def get_table_importance_scores(
    pg_conn: PgConnection,
) -> Dict[str, Dict[str, Any]]:
    """테이블별 중요도 점수 (관계 수 기반)."""
    rows = await pg_conn.fetch(
        """
        SELECT t.name AS table_name, t.schema_name AS schema,
               t.description,
               (SELECT count(*) FROM t2s_fk_constraints fk
                JOIN t2s_columns c ON c.id = fk.from_column_id OR c.id = fk.to_column_id
                WHERE c.table_id = t.id
               ) AS importance_score
        FROM t2s_tables t
        ORDER BY importance_score DESC
        """
    )
    importance_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        importance_map[r["table_name"]] = {
            "schema": r["schema"],
            "description": r["description"],
            "importance_score": r["importance_score"],
        }
    return importance_map


async def get_table_fk_relationships(
    pg_conn: PgConnection,
    table_name: str,
    limit: int,
    schema: Optional[str] = None,
) -> List[Dict]:
    """특정 테이블의 FK 관계 조회 (forward + reverse)."""
    conditions_t = ["(lower(t.name) = lower($1) OR lower(COALESCE(t.original_name, '')) = lower($1))"]
    args: list = [table_name]
    idx = 2
    if schema:
        conditions_t.append(f"lower(t.schema_name) = lower(${idx})")
        args.append(schema)
        idx += 1
    args.append(limit)
    limit_idx = idx

    where_t = " AND ".join(conditions_t)

    forward = await pg_conn.fetch(
        f"""
        SELECT DISTINCT
            COALESCE(t2.original_name, t2.name) AS related_table,
            t2.schema_name AS related_table_schema,
            t2.description AS related_table_description,
            'foreign_key' AS relation_type,
            c1.name AS from_column,
            c1.description AS from_column_description,
            c2.name AS to_column,
            c2.description AS to_column_description
        FROM t2s_tables t
        JOIN t2s_columns c1 ON c1.table_id = t.id
        JOIN t2s_fk_constraints fk ON fk.from_column_id = c1.id
        JOIN t2s_columns c2 ON c2.id = fk.to_column_id
        JOIN t2s_tables t2 ON t2.id = c2.table_id
        WHERE {where_t}
        ORDER BY related_table, c1.name, c2.name
        LIMIT ${limit_idx}
        """,
        *args,
    )
    relationships: List[Dict] = []
    for r in forward:
        rel_info: Dict = {
            "related_table": r["related_table"],
            "related_table_schema": r["related_table_schema"],
            "relation_type": r["relation_type"],
            "from_column": r["from_column"],
            "to_column": r["to_column"],
        }
        if r["related_table_description"]:
            rel_info["related_table_description"] = r["related_table_description"]
        if r["from_column_description"]:
            rel_info["from_column_description"] = r["from_column_description"]
        if r["to_column_description"]:
            rel_info["to_column_description"] = r["to_column_description"]
        relationships.append(rel_info)

    if len(relationships) < limit:
        remaining = limit - len(relationships)
        args_rev = list(args)
        args_rev[-1] = remaining

        reverse = await pg_conn.fetch(
            f"""
            SELECT DISTINCT
                COALESCE(t2.original_name, t2.name) AS related_table,
                t2.schema_name AS related_table_schema,
                t2.description AS related_table_description,
                'referenced_by' AS relation_type,
                c1.name AS from_column,
                c1.description AS from_column_description,
                c2.name AS to_column,
                c2.description AS to_column_description
            FROM t2s_tables t
            JOIN t2s_columns c1 ON c1.table_id = t.id
            JOIN t2s_fk_constraints fk ON fk.to_column_id = c1.id
            JOIN t2s_columns c2 ON c2.id = fk.from_column_id
            JOIN t2s_tables t2 ON t2.id = c2.table_id
            WHERE {where_t}
            ORDER BY related_table, c1.name, c2.name
            LIMIT ${limit_idx}
            """,
            *args_rev,
        )
        for r in reverse:
            rel_info = {
                "related_table": r["related_table"],
                "related_table_schema": r["related_table_schema"],
                "relation_type": r["relation_type"],
                "from_column": r["from_column"],
                "to_column": r["to_column"],
            }
            if r["related_table_description"]:
                rel_info["related_table_description"] = r["related_table_description"]
            if r["from_column_description"]:
                rel_info["from_column_description"] = r["from_column_description"]
            if r["to_column_description"]:
                rel_info["to_column_description"] = r["to_column_description"]
            relationships.append(rel_info)

    relationships.sort(
        key=lambda r: (
            r.get("related_table_schema") or "",
            r.get("related_table") or "",
            r.get("from_column") or "",
            r.get("to_column") or "",
            r.get("relation_type") or "",
        )
    )
    return relationships


async def get_table_any_relationships(
    pg_conn: PgConnection,
    table_name: str,
    schema: Optional[str] = None,
) -> List[Dict]:
    """특정 테이블에서 1-hop FK 이웃 테이블 조회.

    Neo4j에서는 [*1..3] 가변 경로를 사용했으나,
    SQL에서는 1-hop FK JOIN으로 대체 (성능/실용 trade-off).
    """
    conditions = ["(lower(t1.name) = lower($1) OR lower(COALESCE(t1.original_name, '')) = lower($1))"]
    args: list = [table_name]
    idx = 2
    if schema:
        conditions.append(f"lower(t1.schema_name) = lower(${idx})")
        args.append(schema)
        idx += 1

    where = " AND ".join(conditions)
    rows = await pg_conn.fetch(
        f"""
        WITH neighbors AS (
            SELECT DISTINCT t2.id,
                COALESCE(t2.original_name, t2.name) AS related_table,
                t2.schema_name AS related_table_schema,
                COALESCE(t2.comment, t2.description, '설명 없음') AS related_table_description,
                ARRAY['HAS_COLUMN → FK_TO → HAS_COLUMN'] AS relationship_paths
            FROM t2s_tables t1
            JOIN t2s_columns c1 ON c1.table_id = t1.id
            JOIN t2s_fk_constraints fk ON fk.from_column_id = c1.id OR fk.to_column_id = c1.id
            JOIN t2s_columns c2 ON c2.id = CASE
                WHEN fk.from_column_id = c1.id THEN fk.to_column_id
                ELSE fk.from_column_id END
            JOIN t2s_tables t2 ON t2.id = c2.table_id AND t2.id <> t1.id
            WHERE {where}
        )
        SELECT related_table, related_table_schema, related_table_description, relationship_paths
        FROM neighbors
        ORDER BY related_table
        LIMIT 100
        """,
        *args,
    )
    return [
        {
            "related_table": r["related_table"],
            "related_table_schema": r["related_table_schema"],
            "related_table_description": r["related_table_description"],
            "relationship_paths": list(r["relationship_paths"]),
        }
        for r in rows
    ]


async def get_table_relationship_details(
    pg_conn: PgConnection,
    table_name: str,
    relation_limit: int,
    schema: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    if relation_limit <= 0:
        return {"fk_relationships": [], "additional_relationships": []}

    fk_relationships = await get_table_fk_relationships(
        pg_conn, table_name, schema=schema, limit=relation_limit
    )
    fk_related_tables: Set[Tuple[str, str]] = set()
    for rel in fk_relationships:
        related_table = rel.get("related_table")
        if not related_table:
            continue
        fk_related_tables.add((rel.get("related_table_schema") or "", related_table))

    remaining = max(relation_limit - len(fk_relationships), 0)
    additional_relationships: List[Dict[str, Any]] = []

    if remaining:
        candidates = await get_table_any_relationships(pg_conn, table_name, schema=schema)
        scored: List[Dict[str, Any]] = []
        for c in candidates:
            cname = c.get("related_table")
            cschema = c.get("related_table_schema") or ""
            paths = c.get("relationship_paths") or []
            if not cname or (cschema, cname) in fk_related_tables or not paths:
                continue
            score = 0
            labels: List[str] = []
            seen: set = set()
            for p in paths:
                score += RELATIONSHIP_RANKS.get(p, DEFAULT_RELATIONSHIP_SCORE)
                lbl = RELATIONSHIP_TYPE_MAP.get(p)
                if lbl and lbl not in seen:
                    seen.add(lbl)
                    labels.append(lbl)
            scored.append({
                "related_table": cname,
                "related_table_schema": c.get("related_table_schema"),
                "related_table_description": c.get("related_table_description"),
                "relationship_type": ", ".join(labels) if labels else None,
                "score": score,
            })
        scored.sort(key=lambda x: (-x["score"], x["related_table"]))
        additional_relationships = scored[:remaining]

    return {
        "fk_relationships": fk_relationships,
        "additional_relationships": additional_relationships,
    }


async def get_column_fk_relationships(
    pg_conn: PgConnection,
    table_name: str,
    column_name: str,
    limit: int,
    schema: Optional[str] = None,
) -> List[Dict]:
    conditions = [
        "(lower(t.name) = lower($1) OR lower(COALESCE(t.original_name, '')) = lower($1))",
        "lower(c1.name) = lower($2)",
    ]
    args: list = [table_name, column_name]
    idx = 3
    if schema:
        conditions.append(f"lower(t.schema_name) = lower(${idx})")
        args.append(schema)
        idx += 1
    args.append(limit)
    limit_idx = idx

    where = " AND ".join(conditions)
    rows = await pg_conn.fetch(
        f"""
        SELECT
            COALESCE(t2.original_name, t2.name) AS referenced_table,
            t2.schema_name AS referenced_table_schema,
            t2.description AS referenced_table_description,
            c2.name AS referenced_column,
            c2.description AS referenced_column_description,
            fk.constraint_name
        FROM t2s_tables t
        JOIN t2s_columns c1 ON c1.table_id = t.id
        JOIN t2s_fk_constraints fk ON fk.from_column_id = c1.id
        JOIN t2s_columns c2 ON c2.id = fk.to_column_id
        JOIN t2s_tables t2 ON t2.id = c2.table_id
        WHERE {where}
        ORDER BY referenced_table, c2.name
        LIMIT ${limit_idx}
        """,
        *args,
    )
    results: List[Dict] = []
    for r in rows:
        info: Dict = {
            "referenced_table": r["referenced_table"],
            "referenced_column": r["referenced_column"],
        }
        if r["referenced_table_schema"]:
            info["referenced_table_schema"] = r["referenced_table_schema"]
        if r["referenced_table_description"]:
            info["referenced_table_description"] = r["referenced_table_description"]
        if r["referenced_column_description"]:
            info["referenced_column_description"] = r["referenced_column_description"]
        if r["constraint_name"]:
            info["constraint_name"] = r["constraint_name"]
        results.append(info)
    return results
