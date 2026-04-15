"""
PostgreSQL 기반 쿼리 히스토리 저장소 — Neo4jQueryRepository drop-in 대체.

Neo4j의 T2S_Query/ValueMapping 노드 + USES_TABLE/SELECTS/... 관계를
t2s_queries, t2s_value_mappings, t2s_query_table_usage, t2s_query_column_usage
RDB 테이블로 전환한다. 벡터 검색은 pgvector HNSW 인덱스를 사용한다.
"""

from __future__ import annotations

import hashlib
import json as json_module
import logging
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from .pg_connection import PgConnection

logger = logging.getLogger(__name__)


def _vec_str(v: list) -> Optional[str]:
    if not v:
        return None
    return "[" + ",".join(str(float(x)) for x in v) + "]"


class PgQueryRepository:
    """PostgreSQL 기반 쿼리 히스토리 저장소 (Neo4jQueryRepository 대체)."""

    def __init__(self, pg_conn: PgConnection):
        self._pg = pg_conn

    @staticmethod
    def _normalize_question_for_id(question: str) -> str:
        return (question or "").strip()

    def _generate_query_id(self, db: str, question: str) -> str:
        qn = self._normalize_question_for_id(question)
        content = f"{db}:{qn}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    @staticmethod
    def _status_rank(status: Optional[str]) -> int:
        s = (status or "").lower().strip()
        if s == "completed":
            return 0
        if s == "error":
            return 2
        return 1

    @classmethod
    def _candidate_rank(
        cls,
        *,
        status: Optional[str],
        steps_count: Optional[int],
        execution_time_ms: Optional[float],
        best_run_at_ms: Optional[int],
    ) -> Tuple[int, int, float, int]:
        sc = int(steps_count) if steps_count is not None else 10**9
        et = float(execution_time_ms) if execution_time_ms is not None else 1e18
        ts = int(best_run_at_ms) if best_run_at_ms is not None else 0
        return (cls._status_rank(status), sc, et, -ts)

    @staticmethod
    def _minimize_steps_summary(steps: Optional[list]) -> str:
        if not steps:
            return ""
        minimized = []
        for s in steps[-10:]:
            if not isinstance(s, dict):
                continue
            minimized.append({
                "iteration": s.get("iteration"),
                "tool_name": s.get("tool_name"),
                "reasoning": (s.get("reasoning") or "")[:400],
            })
        try:
            return json_module.dumps(minimized, ensure_ascii=False, default=str)
        except Exception:
            return ""

    async def save_query(
        self,
        question: str,
        sql: Optional[str],
        status: str,
        metadata: Optional[Dict] = None,
        row_count: Optional[int] = None,
        execution_time_ms: Optional[float] = None,
        steps_count: Optional[int] = None,
        error_message: Optional[str] = None,
        steps: Optional[list] = None,
        *,
        db: Optional[str] = None,
        steps_summary: Optional[str] = None,
        value_mappings: Optional[List[Dict[str, Any]]] = None,
        best_context_score: Optional[float] = None,
        best_context_steps_features: Optional[Dict[str, Any]] = None,
        best_context_steps_summary: Optional[str] = None,
        verified: bool = False,
        verified_confidence: Optional[float] = None,
        verified_confidence_avg: Optional[float] = None,
        verified_source: Optional[str] = None,
        quality_gate_json: Optional[str] = None,
        react_caching_db_type: str = "",
    ) -> str:
        started = time.perf_counter()
        db_name = (db or react_caching_db_type or "").strip()
        query_id = self._generate_query_id(db_name, question)
        now_ms = int(time.time() * 1000)

        existing = await self._pg.fetchrow(
            """
            SELECT status, steps_count, execution_time_ms, best_run_at_ms,
                   best_context_score, best_context_run_at_ms,
                   verified, quality_gate_json, steps_summary
            FROM t2s_queries WHERE id = $1
            """,
            query_id,
        )

        existing_rank: Optional[Tuple] = None
        existing_context_score: Optional[float] = None
        existing_verified: Optional[bool] = None
        existing_qgj = ""
        existing_ss = ""

        if existing:
            existing_rank = self._candidate_rank(
                status=existing["status"],
                steps_count=existing["steps_count"],
                execution_time_ms=existing["execution_time_ms"],
                best_run_at_ms=existing["best_run_at_ms"],
            )
            existing_context_score = existing["best_context_score"]
            existing_verified = existing["verified"]
            existing_qgj = existing["quality_gate_json"] or ""
            existing_ss = existing["steps_summary"] or ""

        incoming_rank = self._candidate_rank(
            status=status,
            steps_count=steps_count,
            execution_time_ms=execution_time_ms,
            best_run_at_ms=now_ms,
        )
        should_overwrite = existing_rank is None or incoming_rank < existing_rank

        if not should_overwrite:
            if bool(verified) and not bool(existing_verified):
                should_overwrite = True
            else:
                inc_qgj = str(quality_gate_json or "")
                inc_ss = str(steps_summary or "")
                if (inc_qgj and not existing_qgj) or (inc_ss and not existing_ss):
                    should_overwrite = True

        incoming_context_score = float(best_context_score) if best_context_score is not None else 0.0
        eps = 1e-6
        should_overwrite_context = (
            existing_context_score is None
            or incoming_context_score > (existing_context_score or 0.0) + eps
            or (
                incoming_context_score >= (existing_context_score or 0.0)
                and (existing is None or existing["best_context_run_at_ms"] is None or now_ms > existing["best_context_run_at_ms"])
            )
        )

        if steps_summary is None:
            steps_summary = self._minimize_steps_summary(steps)

        vm_count = len(value_mappings or [])
        vm_terms = [(m.get("natural_value") or "") for m in (value_mappings or []) if isinstance(m, dict)][:20]

        bcsf = ""
        if isinstance(best_context_steps_features, dict):
            bcsf = json_module.dumps(best_context_steps_features, ensure_ascii=False, default=str)[:8000]

        if existing is None:
            await self._pg.execute(
                """
                INSERT INTO t2s_queries (
                    id, question, question_norm, sql_text, status, row_count,
                    execution_time_ms, steps_count, error_message, steps_summary,
                    seen_count, verified, verified_confidence, verified_confidence_avg,
                    verified_source, quality_gate_json, value_mappings_count,
                    value_mapping_terms, best_run_at_ms,
                    best_context_score, best_context_steps_features,
                    best_context_steps_summary, best_context_run_at_ms,
                    created_at_ms, updated_at_ms, last_seen_at_ms
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    1, $11, $12, $13,
                    $14, $15, $16,
                    $17, $18,
                    $19, $20,
                    $21, $18,
                    $18, $18, $18
                )
                """,
                query_id, question, self._normalize_question_for_id(question),
                sql, status, row_count,
                execution_time_ms, steps_count, error_message, steps_summary or "",
                bool(verified), verified_confidence, verified_confidence_avg,
                str(verified_source or ""), (quality_gate_json or "")[:8000], vm_count,
                vm_terms, now_ms,
                incoming_context_score, bcsf,
                (best_context_steps_summary or "")[:8000],
            )
        else:
            update_parts = [
                "last_seen_at = now()",
                "last_seen_at_ms = $2",
                "seen_count = COALESCE(seen_count, 0) + 1",
            ]
            args: list = [query_id, now_ms]
            idx = 3

            if should_overwrite:
                fields = [
                    ("sql_text", sql), ("status", status), ("row_count", row_count),
                    ("execution_time_ms", execution_time_ms), ("steps_count", steps_count),
                    ("error_message", error_message), ("steps_summary", steps_summary or ""),
                    ("updated_at", "now()"), ("updated_at_ms", now_ms),
                    ("best_run_at_ms", now_ms), ("value_mappings_count", vm_count),
                    ("value_mapping_terms", vm_terms),
                    ("verified", bool(verified)),
                    ("verified_confidence", verified_confidence),
                    ("verified_confidence_avg", verified_confidence_avg),
                    ("verified_source", str(verified_source or "")),
                    ("quality_gate_json", (quality_gate_json or "")[:8000]),
                ]
                for col, val in fields:
                    if col == "updated_at":
                        update_parts.append("updated_at = now()")
                        continue
                    update_parts.append(f"{col} = ${idx}")
                    args.append(val)
                    idx += 1

            if should_overwrite_context:
                for col, val in [
                    ("best_context_score", incoming_context_score),
                    ("best_context_steps_features", bcsf),
                    ("best_context_steps_summary", (best_context_steps_summary or "")[:8000]),
                    ("best_context_run_at_ms", now_ms),
                ]:
                    update_parts.append(f"{col} = ${idx}")
                    args.append(val)
                    idx += 1

            await self._pg.execute(
                f"UPDATE t2s_queries SET {', '.join(update_parts)} WHERE id = $1",
                *args,
            )

        if should_overwrite and metadata:
            await self._pg.execute(
                "DELETE FROM t2s_query_table_usage WHERE query_id = $1", query_id
            )
            await self._pg.execute(
                "DELETE FROM t2s_query_column_usage WHERE query_id = $1", query_id
            )

            tables_used_list: List[str] = []
            columns_used_list: List[str] = []

            for table in (metadata.get("identified_tables") or []):
                schema = (table.get("schema") or "").strip()
                name = (table.get("name") or "").strip()
                if not schema or not name:
                    continue
                tables_used_list.append(f"{schema}.{name}")
                table_row = await self._pg.fetchrow(
                    """
                    SELECT id FROM t2s_tables
                    WHERE lower(db) = lower($1)
                      AND lower(schema_name) = lower($2)
                      AND (lower(name) = lower($3) OR lower(COALESCE(original_name,'')) = lower($3))
                    LIMIT 1
                    """,
                    db_name, schema, name,
                )
                if table_row:
                    await self._pg.execute(
                        "INSERT INTO t2s_query_table_usage (query_id, table_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        query_id, table_row["id"],
                    )

            for col in (metadata.get("identified_columns") or []):
                purpose = (col.get("purpose") or "SELECT").upper()
                if "FILTER" in purpose or "WHERE" in purpose:
                    rel_type = "FILTERS"
                elif "GROUP" in purpose:
                    rel_type = "GROUPS_BY"
                elif any(fn in purpose for fn in ["AVG", "SUM", "COUNT", "MAX", "MIN"]):
                    rel_type = "AGGREGATES"
                elif "JOIN" in purpose:
                    rel_type = "JOINS_ON"
                else:
                    rel_type = "SELECTS"

                schema = (col.get("schema") or "public").strip()
                table = (col.get("table") or "").strip()
                name = (col.get("name") or "").strip()
                if not table or not name:
                    continue
                fqn = f"{schema}.{table}.{name}"
                columns_used_list.append(fqn)
                col_row = await self._pg.fetchrow(
                    "SELECT id FROM t2s_columns WHERE fqn IS NOT NULL AND lower(fqn) = lower($1) LIMIT 1",
                    fqn,
                )
                if col_row:
                    await self._pg.execute(
                        """
                        INSERT INTO t2s_query_column_usage (query_id, column_id, usage_type)
                        VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
                        """,
                        query_id, col_row["id"], rel_type,
                    )

            await self._pg.execute(
                "UPDATE t2s_queries SET tables_used = $2, columns_used = $3 WHERE id = $1",
                query_id, tables_used_list, columns_used_list,
            )

        logger.debug("save_query done id=%s elapsed=%.1fms", query_id, (time.perf_counter() - started) * 1000)
        return query_id

    async def save_value_mapping_by_fqn(
        self,
        *,
        natural_value: str,
        code_value: str,
        column_fqn: str,
        verified: bool = True,
        verified_confidence: Optional[float] = None,
        verified_source: Optional[str] = "cache_postprocess",
    ) -> None:
        now_ms = int(time.time() * 1000)
        col_row = await self._pg.fetchrow(
            "SELECT id FROM t2s_columns WHERE fqn IS NOT NULL AND lower(fqn) = lower($1) LIMIT 1",
            column_fqn,
        )
        column_id = col_row["id"] if col_row else None
        await self._pg.execute(
            """
            INSERT INTO t2s_value_mappings (
                natural_value, code_value, column_id, column_fqn,
                usage_count, verified, verified_confidence, verified_source,
                verified_at, verified_at_ms
            ) VALUES ($1, $2, $3, $4, 1, $5, $6, $7, now(), $8)
            ON CONFLICT (natural_value, column_fqn) DO UPDATE SET
                code_value = EXCLUDED.code_value,
                column_id = COALESCE(EXCLUDED.column_id, t2s_value_mappings.column_id),
                usage_count = t2s_value_mappings.usage_count + 1,
                verified = EXCLUDED.verified,
                verified_confidence = EXCLUDED.verified_confidence,
                verified_source = EXCLUDED.verified_source,
                verified_at = EXCLUDED.verified_at,
                verified_at_ms = EXCLUDED.verified_at_ms,
                updated_at = now()
            """,
            natural_value, code_value, column_id, column_fqn,
            bool(verified), verified_confidence, str(verified_source or ""), now_ms,
        )

    async def save_value_mapping(
        self,
        natural_value: str,
        code_value: str,
        column_name: str,
    ) -> None:
        col_row = await self._pg.fetchrow(
            "SELECT id, fqn FROM t2s_columns WHERE lower(name) = lower($1) LIMIT 1",
            column_name,
        )
        if not col_row:
            logger.warning("save_value_mapping: column %s not found", column_name)
            return
        column_id = col_row["id"]
        column_fqn = col_row["fqn"] or ""
        await self._pg.execute(
            """
            INSERT INTO t2s_value_mappings (
                natural_value, code_value, column_id, column_fqn, usage_count
            ) VALUES ($1, $2, $3, $4, 1)
            ON CONFLICT (natural_value, column_fqn) DO UPDATE SET
                code_value = EXCLUDED.code_value,
                usage_count = t2s_value_mappings.usage_count + 1,
                updated_at = now()
            """,
            natural_value, code_value, column_id, column_fqn,
        )

    async def find_similar_queries_by_graph(
        self,
        tables: Optional[List[str]] = None,
        columns: Optional[List[str]] = None,
        question_keywords: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict]:
        if tables or columns:
            rows = await self._pg.fetch(
                """
                WITH table_matches AS (
                    SELECT qtu.query_id, count(DISTINCT t.id) AS tm
                    FROM t2s_query_table_usage qtu
                    JOIN t2s_tables t ON t.id = qtu.table_id
                    WHERE lower(t.name) = ANY($1)
                    GROUP BY qtu.query_id
                ),
                column_matches AS (
                    SELECT qcu.query_id, count(DISTINCT c.id) AS cm
                    FROM t2s_query_column_usage qcu
                    JOIN t2s_columns c ON c.id = qcu.column_id
                    WHERE lower(c.name) = ANY($2)
                    GROUP BY qcu.query_id
                )
                SELECT q.id, q.question, q.sql_text AS sql, q.row_count, q.execution_time_ms,
                       COALESCE(tm.tm, 0) * 2 + COALESCE(cm.cm, 0) AS similarity_score
                FROM t2s_queries q
                LEFT JOIN table_matches tm ON tm.query_id = q.id
                LEFT JOIN column_matches cm ON cm.query_id = q.id
                WHERE q.status = 'completed'
                  AND (COALESCE(tm.tm, 0) + COALESCE(cm.cm, 0)) > 0
                ORDER BY similarity_score DESC, q.created_at DESC
                LIMIT $3
                """,
                [t.lower() for t in (tables or [])],
                [c.lower() for c in (columns or [])],
                limit,
            )
        elif question_keywords:
            kw_pattern = "|".join(re.escape(k) for k in question_keywords if k)
            rows = await self._pg.fetch(
                """
                SELECT q.id, q.question, q.sql_text AS sql, q.row_count, q.execution_time_ms,
                       1 AS similarity_score
                FROM t2s_queries q
                WHERE q.status = 'completed'
                  AND q.question ~* $1
                ORDER BY q.created_at DESC
                LIMIT $2
                """,
                kw_pattern, limit,
            )
        else:
            rows = await self._pg.fetch(
                """
                SELECT q.id, q.question, q.sql_text AS sql, q.row_count, q.execution_time_ms,
                       0 AS similarity_score
                FROM t2s_queries q
                WHERE q.status = 'completed'
                ORDER BY q.created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def find_value_mapping(self, natural_value: str) -> List[Dict]:
        rows = await self._pg.fetch(
            """
            SELECT vm.natural_value, vm.code_value, vm.column_fqn,
                   c.name AS column_name, vm.usage_count
            FROM t2s_value_mappings vm
            LEFT JOIN t2s_columns c ON c.id = vm.column_id
            WHERE lower(vm.natural_value) LIKE '%' || lower($1) || '%'
            ORDER BY vm.usage_count DESC
            LIMIT 10
            """,
            natural_value,
        )
        return [dict(r) for r in rows]

    async def get_query_history(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> Dict:
        skip = (page - 1) * page_size
        if status:
            items_rows = await self._pg.fetch(
                """
                SELECT q.id, q.question, q.sql_text AS sql, q.status,
                       q.row_count, q.execution_time_ms, q.steps_count,
                       q.created_at,
                       COALESCE(
                         (SELECT array_agg(t.name) FROM t2s_query_table_usage qtu
                          JOIN t2s_tables t ON t.id = qtu.table_id
                          WHERE qtu.query_id = q.id),
                         '{}'
                       ) AS tables
                FROM t2s_queries q
                WHERE q.status = $1
                ORDER BY q.created_at DESC
                OFFSET $2 LIMIT $3
                """,
                status, skip, page_size,
            )
            total = await self._pg.fetchval(
                "SELECT count(*) FROM t2s_queries WHERE status = $1", status
            )
        else:
            items_rows = await self._pg.fetch(
                """
                SELECT q.id, q.question, q.sql_text AS sql, q.status,
                       q.row_count, q.execution_time_ms, q.steps_count,
                       q.created_at,
                       COALESCE(
                         (SELECT array_agg(t.name) FROM t2s_query_table_usage qtu
                          JOIN t2s_tables t ON t.id = qtu.table_id
                          WHERE qtu.query_id = q.id),
                         '{}'
                       ) AS tables
                FROM t2s_queries q
                ORDER BY q.created_at DESC
                OFFSET $1 LIMIT $2
                """,
                skip, page_size,
            )
            total = await self._pg.fetchval("SELECT count(*) FROM t2s_queries")

        return {
            "items": [dict(r) for r in items_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_table_usage_stats(self) -> List[Dict]:
        rows = await self._pg.fetch(
            """
            SELECT t.schema_name AS schema, t.name AS table_name,
                   count(qtu.query_id) AS usage_count,
                   (SELECT array_agg(DISTINCT sub.question)
                    FROM (
                      SELECT q2.question
                      FROM t2s_query_table_usage qtu2
                      JOIN t2s_queries q2 ON q2.id = qtu2.query_id
                      WHERE qtu2.table_id = t.id AND q2.status = 'completed'
                      LIMIT 3
                    ) sub
                   ) AS sample_questions
            FROM t2s_query_table_usage qtu
            JOIN t2s_tables t ON t.id = qtu.table_id
            JOIN t2s_queries q ON q.id = qtu.query_id AND q.status = 'completed'
            GROUP BY t.id, t.schema_name, t.name
            ORDER BY usage_count DESC
            LIMIT 20
            """
        )
        return [dict(r) for r in rows]

    async def get_column_usage_stats(self) -> List[Dict]:
        rows = await self._pg.fetch(
            """
            SELECT c.fqn AS column_fqn, c.name AS column_name,
                   qcu.usage_type, count(qcu.query_id) AS usage_count
            FROM t2s_query_column_usage qcu
            JOIN t2s_columns c ON c.id = qcu.column_id
            JOIN t2s_queries q ON q.id = qcu.query_id AND q.status = 'completed'
            GROUP BY c.fqn, c.name, qcu.usage_type
            ORDER BY usage_count DESC
            LIMIT 30
            """
        )
        return [dict(r) for r in rows]

    async def delete_query(self, query_id: str) -> bool:
        result = await self._pg.execute(
            "DELETE FROM t2s_queries WHERE id = $1", query_id
        )
        return "DELETE 1" in result
