"""
build_sql_context_parts/neo4j.py 핵심 함수 pgvector+SQL 전환.

모든 _neo4j_* 함수를 pg_* 동일 시그니처로 대체한다.
context 객체는 neo4j_session 대신 pg_conn: PgConnection을 사용한다.

함수 매핑:
  _neo4j_search_tables_text2sql_vector → pg_search_tables_text2sql_vector
  _neo4j_fetch_tables_by_names         → pg_fetch_tables_by_names
  _neo4j_fetch_table_embedding_texts   → pg_fetch_table_embedding_texts
  _neo4j_fetch_table_embedding_texts_for_tables → pg_fetch_table_embedding_texts_for_tables
  _neo4j_fetch_fk_neighbors_1hop       → pg_fetch_fk_neighbors_1hop
  _neo4j_search_table_scoped_columns   → pg_search_table_scoped_columns
  _neo4j_fetch_anchor_like_columns_for_tables → pg_fetch_anchor_like_columns_for_tables
  _neo4j_search_columns                → pg_search_columns
  _neo4j_find_similar_queries_and_mappings → pg_find_similar_queries_and_mappings
  _neo4j_fetch_table_schemas           → pg_fetch_table_schemas
  _neo4j_fetch_fk_relationships        → pg_fetch_fk_relationships
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pg_connection import PgConnection

logger = logging.getLogger(__name__)


def _vec_str(v: list) -> Optional[str]:
    if not v:
        return None
    return "[" + ",".join(str(float(x)) for x in v) + "]"


# ──────────────────────────────────────────────────────────────
# 데이터 클래스 (build_sql_context_parts/models.py 호환)
# 원본 코드에서 from .models import TableCandidate, ColumnCandidate
# 여기서는 동일 구조를 제공하되 독립적으로 사용 가능하게 한다.
# ──────────────────────────────────────────────────────────────

class TableCandidate:
    __slots__ = ("schema", "name", "description", "analyzed_description", "score")

    def __init__(
        self,
        schema: str = "",
        name: str = "",
        description: str = "",
        analyzed_description: str = "",
        score: float = 0.0,
    ):
        self.schema = schema
        self.name = name
        self.description = description
        self.analyzed_description = analyzed_description
        self.score = score


class ColumnCandidate:
    __slots__ = ("table_schema", "table_name", "name", "dtype", "description", "score")

    def __init__(
        self,
        table_schema: str = "",
        table_name: str = "",
        name: str = "",
        dtype: str = "",
        description: str = "",
        score: float = 0.0,
    ):
        self.table_schema = table_schema
        self.table_name = table_name
        self.name = name
        self.dtype = dtype
        self.description = description
        self.score = score


# ──────────────────────────────────────────────────────────────
# 테이블 검색
# ──────────────────────────────────────────────────────────────

async def pg_search_tables_text2sql_vector(
    *,
    pg_conn: PgConnection,
    embedding: List[float],
    k: int,
    schema_filter: Optional[Sequence[str]] = None,
) -> Tuple[List[TableCandidate], str]:
    """text_to_sql_vector 기반 테이블 검색 (HNSW 코사인 유사도)."""
    k = max(1, int(k))
    conditions = [
        "text_to_sql_vector IS NOT NULL",
        "COALESCE(text_to_sql_is_valid, true) = true",
    ]
    args: list = [_vec_str(embedding), k]
    idx = 3

    sf_lower = [s.strip().lower() for s in (schema_filter or []) if s and s.strip()]
    if sf_lower:
        conditions.append(f"lower(COALESCE(schema_name, '')) = ANY(${idx})")
        args.append(sf_lower)
        idx += 1

    where = " AND ".join(conditions)
    sql = f"""
    SELECT
      COALESCE(schema_name, '') AS schema,
      COALESCE(name, '') AS name,
      COALESCE(description, '') AS description,
      COALESCE(analyzed_description, '') AS analyzed_description,
      1 - (text_to_sql_vector <=> $1::vector) AS score
    FROM t2s_tables
    WHERE {where}
    ORDER BY text_to_sql_vector <=> $1::vector
    LIMIT $2
    """
    rows = await pg_conn.fetch(sql, *args)
    out = [
        TableCandidate(
            schema=r["schema"], name=r["name"],
            description=r["description"],
            analyzed_description=r["analyzed_description"],
            score=float(r["score"]),
        )
        for r in rows
    ]
    return out, "pgvector_hnsw"


async def pg_fetch_tables_by_names(
    *,
    pg_conn: PgConnection,
    names: Sequence[str],
    schema: Optional[str],
) -> List[TableCandidate]:
    cleaned = [str(x).strip().lower() for x in (names or []) if str(x or "").strip()][:200]
    if not cleaned:
        return []
    args: list = [cleaned]
    conditions = [
        "lower(COALESCE(name, '')) = ANY($1)",
        "COALESCE(text_to_sql_is_valid, true) = true",
    ]
    idx = 2
    if schema:
        conditions.append(f"lower(COALESCE(schema_name, '')) = lower(${idx})")
        args.append(schema)
        idx += 1

    where = " AND ".join(conditions)
    rows = await pg_conn.fetch(
        f"""
        SELECT COALESCE(schema_name, '') AS schema,
               COALESCE(name, '') AS name,
               COALESCE(description, '') AS description,
               COALESCE(analyzed_description, '') AS analyzed_description
        FROM t2s_tables WHERE {where}
        """,
        *args,
    )
    return [
        TableCandidate(schema=r["schema"], name=r["name"],
                       description=r["description"],
                       analyzed_description=r["analyzed_description"])
        for r in rows
    ]


async def pg_fetch_table_embedding_texts(
    *,
    pg_conn: PgConnection,
    names: Sequence[str],
    schema: Optional[str],
) -> Dict[str, str]:
    cleaned = [str(x).strip().lower() for x in (names or []) if str(x or "").strip()][:200]
    if not cleaned:
        return {}
    args: list = [cleaned]
    conditions = ["lower(COALESCE(name, '')) = ANY($1)"]
    idx = 2
    if schema:
        conditions.append(f"lower(COALESCE(schema_name, '')) = lower(${idx})")
        args.append(schema)

    where = " AND ".join(conditions)
    rows = await pg_conn.fetch(
        f"""
        SELECT COALESCE(schema_name, '') AS schema,
               COALESCE(name, '') AS name,
               COALESCE(text_to_sql_embedding_text, '') AS embedding_text
        FROM t2s_tables WHERE {where}
        """,
        *args,
    )
    out: Dict[str, str] = {}
    for r in rows:
        fqn = f"{r['schema']}.{r['name']}" if r["schema"] else r["name"]
        out[fqn.lower()] = r["embedding_text"]
    return out


async def pg_fetch_table_embedding_texts_for_tables(
    *,
    pg_conn: PgConnection,
    tables: Sequence[TableCandidate],
) -> Dict[str, str]:
    names = []
    schemas = []
    for t in (tables or []):
        name = (t.name or "").strip()
        if not name:
            continue
        names.append(name.lower())
        schemas.append((t.schema or "").strip().lower() or None)

    if not names:
        return {}

    rows = await pg_conn.fetch(
        """
        SELECT COALESCE(schema_name, '') AS schema,
               COALESCE(name, '') AS name,
               COALESCE(text_to_sql_embedding_text, '') AS embedding_text
        FROM t2s_tables
        WHERE lower(name) = ANY($1) OR lower(COALESCE(original_name, '')) = ANY($1)
        """,
        names,
    )
    out: Dict[str, str] = {}
    for r in rows:
        fqn = f"{r['schema']}.{r['name']}" if r["schema"] else r["name"]
        out[fqn.lower()] = r["embedding_text"]
    return out


# ──────────────────────────────────────────────────────────────
# FK 이웃 확장
# ──────────────────────────────────────────────────────────────

async def pg_fetch_fk_neighbors_1hop(
    *,
    pg_conn: PgConnection,
    seed_fqns: Sequence[str],
    schema: Optional[str],
    limit: int,
) -> List[TableCandidate]:
    seeds = [str(x).strip().lower() for x in (seed_fqns or []) if str(x or "").strip()][:200]
    if not seeds:
        return []

    conditions = ["COALESCE(t2.text_to_sql_is_valid, true) = true"]
    args: list = [seeds, max(1, int(limit))]
    idx = 3
    if schema:
        conditions.append(f"lower(COALESCE(t2.schema_name, '')) = lower(${idx})")
        args.append(schema)

    extra_where = " AND ".join(conditions)
    rows = await pg_conn.fetch(
        f"""
        SELECT DISTINCT
          COALESCE(t2.schema_name, '') AS schema,
          COALESCE(t2.name, '') AS name,
          COALESCE(t2.description, '') AS description,
          COALESCE(t2.analyzed_description, '') AS analyzed_description
        FROM t2s_tables t1
        JOIN t2s_columns c1 ON c1.table_id = t1.id
        JOIN t2s_fk_constraints fk ON fk.from_column_id = c1.id
        JOIN t2s_columns c2 ON c2.id = fk.to_column_id
        JOIN t2s_tables t2 ON t2.id = c2.table_id
        WHERE (lower(COALESCE(t1.schema_name,'')) || '.' || lower(COALESCE(t1.name,''))) = ANY($1)
          AND {extra_where}
        LIMIT $2
        """,
        *args,
    )
    return [
        TableCandidate(
            schema=r["schema"], name=r["name"],
            description=r["description"],
            analyzed_description=r["analyzed_description"],
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
# 컬럼 검색
# ──────────────────────────────────────────────────────────────

async def pg_search_table_scoped_columns(
    *,
    pg_conn: PgConnection,
    embedding: List[float],
    tables: Sequence[TableCandidate],
    per_table_k: int,
) -> Tuple[Dict[str, List[ColumnCandidate]], str]:
    """테이블 스코프 내 컬럼 코사인 유사도 검색."""
    per_table_k = max(1, int(per_table_k))
    names = []
    for t in tables:
        name = (t.name or "").strip()
        if name:
            names.append(name.lower())
    if not names:
        return {}, "no_tables"

    rows = await pg_conn.fetch(
        """
        WITH ranked AS (
            SELECT
              COALESCE(t.schema_name, '') AS table_schema,
              COALESCE(t.original_name, t.name) AS table_name,
              c.name,
              c.dtype,
              COALESCE(c.description, '') AS description,
              1 - (c.vector <=> $1::vector) AS score,
              ROW_NUMBER() OVER (
                PARTITION BY t.id
                ORDER BY c.vector <=> $1::vector
              ) AS rn
            FROM t2s_columns c
            JOIN t2s_tables t ON t.id = c.table_id
            WHERE c.vector IS NOT NULL
              AND COALESCE(t.text_to_sql_is_valid, true) = true
              AND COALESCE(c.text_to_sql_is_valid, true) = true
              AND (lower(t.name) = ANY($2) OR lower(COALESCE(t.original_name, '')) = ANY($2))
        )
        SELECT table_schema, table_name, name, dtype, description, score
        FROM ranked
        WHERE rn <= $3
        ORDER BY table_schema, table_name, score DESC
        """,
        _vec_str(embedding), names, per_table_k,
    )
    out: Dict[str, List[ColumnCandidate]] = {}
    for r in rows:
        schema_l = (r["table_schema"] or "").lower()
        name_l = (r["table_name"] or "").lower()
        tfqn_l = f"{schema_l}.{name_l}" if schema_l else name_l
        if tfqn_l not in out:
            out[tfqn_l] = []
        out[tfqn_l].append(
            ColumnCandidate(
                table_schema=r["table_schema"], table_name=r["table_name"],
                name=r["name"], dtype=r["dtype"],
                description=r["description"], score=float(r["score"]),
            )
        )
    return out, "pgvector_table_scoped"


async def pg_fetch_anchor_like_columns_for_tables(
    *,
    pg_conn: PgConnection,
    tables: Sequence[TableCandidate],
    name_substrings_lower: Sequence[str],
    keywords_lower: Sequence[str],
    per_table_limit: int = 10,
) -> List[ColumnCandidate]:
    names = []
    for t in tables:
        name = (t.name or "").strip()
        if name:
            names.append(name.lower())
    if not names:
        return []

    subs = [str(s or "").strip().lower() for s in name_substrings_lower if str(s or "").strip()][:20]
    kws = [str(k or "").strip().lower() for k in keywords_lower if str(k or "").strip()][:20]
    if not subs and not kws:
        return []

    sub_conditions = []
    for s in subs:
        sub_conditions.append(f"lower(c.name) LIKE '%{s}%'")
    for kw in kws:
        sub_conditions.append(f"lower(c.name) LIKE '%{kw}%'")
        sub_conditions.append(f"lower(COALESCE(c.description, '')) LIKE '%{kw}%'")

    match_clause = " OR ".join(sub_conditions) if sub_conditions else "false"

    rows = await pg_conn.fetch(
        f"""
        WITH ranked AS (
            SELECT
              COALESCE(t.schema_name, '') AS table_schema,
              COALESCE(t.original_name, t.name) AS table_name,
              c.name, c.dtype, COALESCE(c.description, '') AS description,
              ROW_NUMBER() OVER (PARTITION BY t.id ORDER BY c.name) AS rn
            FROM t2s_columns c
            JOIN t2s_tables t ON t.id = c.table_id
            WHERE (lower(t.name) = ANY($1) OR lower(COALESCE(t.original_name, '')) = ANY($1))
              AND COALESCE(t.text_to_sql_is_valid, true) = true
              AND COALESCE(c.text_to_sql_is_valid, true) = true
              AND ({match_clause})
        )
        SELECT table_schema, table_name, name, dtype, description
        FROM ranked WHERE rn <= $2
        ORDER BY table_schema, table_name, name
        """,
        names, per_table_limit,
    )
    return [
        ColumnCandidate(
            table_schema=r["table_schema"], table_name=r["table_name"],
            name=r["name"], dtype=r["dtype"],
            description=r["description"], score=0.5,
        )
        for r in rows
    ]


async def pg_search_columns(
    *,
    pg_conn: PgConnection,
    embedding: List[float],
    k: int,
) -> List[ColumnCandidate]:
    rows = await pg_conn.fetch(
        """
        SELECT c.name,
               t.schema_name AS table_schema,
               COALESCE(t.original_name, t.name) AS table_name,
               c.dtype, COALESCE(c.description, '') AS description,
               1 - (c.vector <=> $1::vector) AS score
        FROM t2s_columns c
        JOIN t2s_tables t ON t.id = c.table_id
        WHERE c.vector IS NOT NULL
          AND COALESCE(t.text_to_sql_is_valid, true) = true
          AND COALESCE(c.text_to_sql_is_valid, true) = true
        ORDER BY c.vector <=> $1::vector
        LIMIT $2
        """,
        _vec_str(embedding), int(k),
    )
    return [
        ColumnCandidate(
            table_schema=r["table_schema"], table_name=r["table_name"],
            name=r["name"], dtype=r["dtype"],
            description=r["description"], score=float(r["score"]),
        )
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────
# 유사 쿼리 + 값 매핑 검색
# ──────────────────────────────────────────────────────────────

async def pg_find_similar_queries_and_mappings(
    *,
    pg_conn: PgConnection,
    question: str,
    question_embedding: List[float],
    intent_embedding: Optional[List[float]] = None,
    terms: Sequence[str],
    min_similarity: float = 0.3,
    use_verified_only: bool = True,
    allow_vm_substring_fallback: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """유사 쿼리 벡터 검색 + 값 매핑 조회 (pgvector)."""
    fetch_k = 20
    limit_k = 5

    verified_clause = "AND COALESCE(verified, false) = true" if use_verified_only else ""

    q_sql = f"""
    SELECT id, question, sql_text AS sql, steps_count, execution_time_ms,
           tables_used, columns_used, best_run_at_ms,
           best_context_score, best_context_steps_features,
           best_context_steps_summary,
           1 - (vector_question <=> $1::vector) AS similarity_score
    FROM t2s_queries
    WHERE vector_question IS NOT NULL
      AND status = 'completed'
      AND sql_text IS NOT NULL
      {verified_clause}
      AND 1 - (vector_question <=> $1::vector) >= $3
    ORDER BY vector_question <=> $1::vector
    LIMIT $2
    """
    q_rows = await pg_conn.fetch(q_sql, _vec_str(question_embedding), fetch_k, min_similarity)

    i_rows: list = []
    if intent_embedding:
        i_sql = f"""
        SELECT id, question, sql_text AS sql, steps_count, execution_time_ms,
               tables_used, columns_used, best_run_at_ms,
               best_context_score, best_context_steps_features,
               best_context_steps_summary,
               1 - (vector_intent <=> $1::vector) AS similarity_score
        FROM t2s_queries
        WHERE vector_intent IS NOT NULL
          AND status = 'completed'
          AND sql_text IS NOT NULL
          {verified_clause}
          AND 1 - (vector_intent <=> $1::vector) >= $3
        ORDER BY vector_intent <=> $1::vector
        LIMIT $2
        """
        i_rows = await pg_conn.fetch(i_sql, _vec_str(intent_embedding), fetch_k, min_similarity)

    by_id: Dict[str, Dict[str, Any]] = {}
    for r in q_rows:
        qid = str(r["id"] or "")
        if not qid:
            continue
        base = dict(r)
        base["_question_score"] = float(r["similarity_score"])
        base["_intent_score"] = 0.0
        by_id[qid] = base

    for r in i_rows:
        qid = str(r["id"] or "")
        if not qid:
            continue
        if qid not in by_id:
            base = dict(r)
            base["_question_score"] = 0.0
            base["_intent_score"] = float(r["similarity_score"])
            by_id[qid] = base
        else:
            by_id[qid]["_intent_score"] = max(
                float(by_id[qid].get("_intent_score") or 0.0),
                float(r["similarity_score"]),
            )

    use_intent = bool(intent_embedding)
    for r in by_id.values():
        q_score = float(r.get("_question_score") or 0.0)
        i_score = float(r.get("_intent_score") or 0.0)
        final = (0.6 * i_score + 0.4 * q_score) if use_intent else q_score
        r["similarity_score"] = final
        r["question_similarity_score"] = q_score
        r["intent_similarity_score"] = i_score

    similar_queries = sorted(
        by_id.values(),
        key=lambda x: (float(x.get("similarity_score") or 0.0), int(x.get("best_run_at_ms") or 0)),
        reverse=True,
    )[:limit_k]

    value_mappings: List[Dict[str, Any]] = []
    if terms:
        cleaned_terms = [str(t or "").strip() for t in list(terms)[:50] if str(t or "").strip()]
        vm_verified = "AND COALESCE(vm.verified, false) = true" if use_verified_only else ""

        vm_rows = await pg_conn.fetch(
            f"""
            SELECT vm.natural_value, vm.code_value, vm.column_fqn,
                   c.name AS column_name, vm.usage_count
            FROM t2s_value_mappings vm
            LEFT JOIN t2s_columns c ON c.id = vm.column_id
            WHERE vm.natural_value = ANY($1)
              {vm_verified}
            ORDER BY vm.usage_count DESC
            LIMIT 20
            """,
            cleaned_terms,
        )
        value_mappings = [dict(r) for r in vm_rows]

        if allow_vm_substring_fallback and not value_mappings and cleaned_terms:
            like_patterns = [f"%{t}%" for t in cleaned_terms]
            vm_rows2 = await pg_conn.fetch(
                f"""
                SELECT vm.natural_value, vm.code_value, vm.column_fqn,
                       c.name AS column_name, vm.usage_count
                FROM t2s_value_mappings vm
                LEFT JOIN t2s_columns c ON c.id = vm.column_id
                WHERE EXISTS (
                    SELECT 1 FROM unnest($1::text[]) pat
                    WHERE lower(vm.natural_value) LIKE lower(pat)
                )
                  {vm_verified}
                ORDER BY vm.usage_count DESC
                LIMIT 20
                """,
                like_patterns,
            )
            value_mappings = [dict(r) for r in vm_rows2]

    return similar_queries, value_mappings


# ──────────────────────────────────────────────────────────────
# 테이블 스키마 / FK 조회
# ──────────────────────────────────────────────────────────────

async def pg_fetch_table_schemas(
    *,
    pg_conn: PgConnection,
    tables: Sequence[TableCandidate],
) -> List[Dict[str, Any]]:
    names = []
    for t in (tables or []):
        name = (t.name or "").strip()
        if name:
            names.append(name.lower())
    if not names:
        return []

    rows = await pg_conn.fetch(
        """
        SELECT
          COALESCE(t.original_name, t.name) AS table_name,
          t.schema_name AS table_schema,
          t.description AS table_description,
          c.name, c.fqn, c.dtype, c.nullable, c.description AS col_description,
          c.is_primary_key, c.enum_values, c.cardinality
        FROM t2s_tables t
        LEFT JOIN t2s_columns c ON c.table_id = t.id
          AND COALESCE(c.text_to_sql_is_valid, true) = true
        WHERE COALESCE(t.text_to_sql_is_valid, true) = true
          AND (lower(t.name) = ANY($1) OR lower(COALESCE(t.original_name, '')) = ANY($1))
        ORDER BY t.schema_name, t.name, c.name
        """,
        names,
    )

    tables_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['table_schema']}.{r['table_name']}".lower()
        if key not in tables_map:
            tables_map[key] = {
                "schema": r["table_schema"] or "",
                "name": r["table_name"] or "",
                "description": r["table_description"] or "",
                "columns": [],
            }
        if r["name"]:
            tables_map[key]["columns"].append({
                "name": r["name"],
                "fqn": r["fqn"],
                "dtype": r["dtype"],
                "nullable": r["nullable"],
                "description": r["col_description"],
                "is_primary_key": r["is_primary_key"],
                "enum_values": r["enum_values"],
                "cardinality": r["cardinality"],
            })

    return list(tables_map.values())


async def pg_fetch_fk_relationships(
    *,
    pg_conn: PgConnection,
    table_fqns: Sequence[str],
    limit: int = 30,
) -> List[Dict[str, Any]]:
    if not table_fqns:
        return []
    fqns_l = [str(x or "").strip().lower() for x in table_fqns if str(x or "").strip()]

    rows = await pg_conn.fetch(
        """
        SELECT
          COALESCE(t1.original_name, t1.name) AS from_table,
          t1.schema_name AS from_schema,
          c1.name AS from_column,
          COALESCE(t2.original_name, t2.name) AS to_table,
          t2.schema_name AS to_schema,
          c2.name AS to_column,
          fk.constraint_name
        FROM t2s_fk_constraints fk
        JOIN t2s_columns c1 ON c1.id = fk.from_column_id
        JOIN t2s_columns c2 ON c2.id = fk.to_column_id
        JOIN t2s_tables t1 ON t1.id = c1.table_id
        JOIN t2s_tables t2 ON t2.id = c2.table_id
        WHERE COALESCE(t1.text_to_sql_is_valid, true) = true
          AND COALESCE(t2.text_to_sql_is_valid, true) = true
          AND COALESCE(c1.text_to_sql_is_valid, true) = true
          AND COALESCE(c2.text_to_sql_is_valid, true) = true
          AND (lower(COALESCE(t1.schema_name,'')) || '.' || lower(COALESCE(t1.original_name, t1.name))) = ANY($1)
          AND (lower(COALESCE(t2.schema_name,'')) || '.' || lower(COALESCE(t2.original_name, t2.name))) = ANY($1)
        ORDER BY from_schema, from_table, to_schema, to_table, from_column, to_column
        LIMIT $2
        """,
        fqns_l, int(limit),
    )
    return [dict(r) for r in rows]


__all__ = [
    "TableCandidate",
    "ColumnCandidate",
    "pg_search_tables_text2sql_vector",
    "pg_fetch_tables_by_names",
    "pg_fetch_table_embedding_texts",
    "pg_fetch_table_embedding_texts_for_tables",
    "pg_fetch_fk_neighbors_1hop",
    "pg_search_table_scoped_columns",
    "pg_fetch_anchor_like_columns_for_tables",
    "pg_search_columns",
    "pg_find_similar_queries_and_mappings",
    "pg_fetch_table_schemas",
    "pg_fetch_fk_relationships",
]
