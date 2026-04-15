"""
PgAnalyzerClient — Neo4jClient의 drop-in 대체.

Neo4jClient의 5가지 핵심 메서드를 PostgreSQL(asyncpg)로 전환:
  - execute_queries → SQL 실행 + 결과 반환
  - run_graph_query → SQL 배치 실행 + 노드/관계 구조 yield
  - execute_with_params → parameterized SQL 실행
  - run_batch_unwind → 배치 SQL + 그래프 결과
  - check_nodes_exist → EXISTS 쿼리

analyzer_tables, analyzer_columns 등 RDB 테이블에 직접 CRUD합니다.
"""

import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import asyncpg

logger = logging.getLogger(__name__)


class PgAnalyzerClient:
    """PostgreSQL 기반 Analyzer 클라이언트 — Neo4jClient 대체"""

    __slots__ = ("_pool", "_lock", "_batch_size")

    def __init__(self, pool: asyncpg.Pool, batch_size: int = 30):
        self._pool = pool
        self._lock = asyncio.Lock()
        self._batch_size = batch_size

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def close(self):
        pass

    # ------------------------------------------------------------------
    # 1. execute_queries — 순차 SQL 실행, 결과 반환
    # ------------------------------------------------------------------
    async def execute_queries(
        self,
        queries: List[str | Dict[str, Any]],
        params: Optional[Dict] = None,
    ) -> List[List[Dict[str, Any]]]:
        if not queries:
            return []

        results: List[List[Dict[str, Any]]] = []
        async with self._pool.acquire() as conn:
            for query in queries:
                if isinstance(query, dict):
                    query_str = query.get("query") or query.get("sql", "")
                    item_params = query.get("parameters") or query.get("params") or {}
                    merged = {**(params or {}), **item_params}
                else:
                    query_str = query
                    merged = params or {}

                sql, args = _convert_named_params(query_str.strip(), merged)
                try:
                    rows = await conn.fetch(sql, *args)
                    results.append([dict(r) for r in rows])
                except Exception as e:
                    raise RuntimeError(f"SQL 실행 오류: {e}\nSQL: {sql[:200]}") from e
        return results

    # ------------------------------------------------------------------
    # 2. run_graph_query — 배치 실행, 노드/관계 딕셔너리 yield
    # ------------------------------------------------------------------
    async def run_graph_query(
        self,
        queries: List[str | Dict[str, Any]],
        batch_size: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not queries:
            yield {"Nodes": [], "Relationships": [], "batch": 0, "total_batches": 0}
            return

        bs = batch_size or self._batch_size
        total_batches = (len(queries) + bs - 1) // bs

        async with self._pool.acquire() as conn:
            for batch_idx in range(total_batches):
                start = batch_idx * bs
                end = min(start + bs, len(queries))
                batch_queries = queries[start:end]

                nodes: Dict[str, Dict] = {}
                relationships: Dict[str, Dict] = {}

                for query in batch_queries:
                    if isinstance(query, dict):
                        query_str = query.get("query") or query.get("sql", "")
                        item_params = query.get("params") or query.get("parameters") or {}
                    else:
                        query_str = query
                        item_params = {}

                    sql, args = _convert_named_params(query_str.strip(), item_params)
                    try:
                        rows = await conn.fetch(sql, *args)
                        for row in rows:
                            record = dict(row)
                            _extract_graph_entities(record, nodes, relationships)
                    except Exception as e:
                        logger.warning("run_graph_query batch SQL 오류: %s", e)

                yield {
                    "Nodes": list(nodes.values()),
                    "Relationships": list(relationships.values()),
                    "batch": batch_idx + 1,
                    "total_batches": total_batches,
                }

    # ------------------------------------------------------------------
    # 3. execute_with_params — 단일 SQL + params
    # ------------------------------------------------------------------
    async def execute_with_params(
        self,
        query: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        sql, args = _convert_named_params(query.strip(), params)
        async with self._pool.acquire() as conn:
            try:
                rows = await conn.fetch(sql, *args)
                return [dict(r) for r in rows]
            except Exception as e:
                raise RuntimeError(f"파라미터 SQL 실행 오류: {e}") from e

    # ------------------------------------------------------------------
    # 4. run_batch_unwind — 배치 SQL + 그래프 결과
    # ------------------------------------------------------------------
    async def run_batch_unwind(
        self,
        query: str,
        items: List[Dict],
        batch_size: int = 500,
    ) -> Dict[str, List]:
        if not items:
            return {"Nodes": [], "Relationships": []}

        nodes: Dict[str, Dict] = {}
        relationships: Dict[str, Dict] = {}

        async with self._pool.acquire() as conn:
            for i in range(0, len(items), batch_size):
                batch = items[i : i + batch_size]
                sql, args = _convert_named_params(query.strip(), {"items": batch})
                try:
                    rows = await conn.fetch(sql, *args)
                    for row in rows:
                        record = dict(row)
                        _extract_graph_entities(record, nodes, relationships)
                except Exception as e:
                    logger.warning("run_batch_unwind SQL 오류: %s", e)

        return {
            "Nodes": list(nodes.values()),
            "Relationships": list(relationships.values()),
        }

    # ------------------------------------------------------------------
    # 5. check_nodes_exist
    # ------------------------------------------------------------------
    async def check_nodes_exist(
        self,
        file_names: List[Tuple[str, str]],
    ) -> bool:
        if not file_names:
            return False

        async with self._pool.acquire() as conn:
            for directory, file_name in file_names:
                row = await conn.fetchrow(
                    "SELECT 1 FROM analyzer_ast_nodes WHERE directory = $1 AND file_name = $2 LIMIT 1",
                    directory,
                    file_name,
                )
                if row:
                    return True
        return False

    # ------------------------------------------------------------------
    # 6. ensure_constraints (no-op: DDL 이미 제약조건 포함)
    # ------------------------------------------------------------------
    async def ensure_constraints(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Convenience: acquire raw connection
    # ------------------------------------------------------------------
    def acquire(self):
        return self._pool.acquire()


# =====================================================================
# Helper: named-param conversion ($name → $1, $2, ...)
# =====================================================================

def _convert_named_params(
    sql: str, params: Dict[str, Any]
) -> Tuple[str, List[Any]]:
    """$name 스타일 파라미터를 asyncpg의 $1,$2,... 스타일로 변환.
    
    params 딕셔너리가 비어있거나 sql에 $name이 없으면 그대로 반환.
    """
    if not params:
        return sql, []

    import re

    used_params: List[str] = []
    param_map: Dict[str, int] = {}

    def _replacer(match):
        name = match.group(1)
        if name not in param_map:
            param_map[name] = len(used_params) + 1
            used_params.append(name)
        return f"${param_map[name]}"

    converted = re.sub(r"\$([a-zA-Z_][a-zA-Z0-9_]*)", _replacer, sql)
    args = [params.get(name) for name in used_params]
    return converted, args


def _extract_graph_entities(
    record: Dict[str, Any],
    nodes: Dict[str, Dict],
    relationships: Dict[str, Dict],
) -> None:
    """SQL 결과 행에서 그래프 노드/관계 형태로 추출 (호환 구조)."""
    node_id = record.get("node_id") or record.get("id")
    if node_id is not None:
        key = str(node_id)
        if key not in nodes:
            labels = record.get("labels") or record.get("node_type")
            if isinstance(labels, str):
                labels = [labels]
            elif labels is None:
                labels = []
            nodes[key] = {
                "Node ID": key,
                "Labels": labels,
                "Properties": {
                    k: v
                    for k, v in record.items()
                    if k not in ("node_id", "labels", "node_type", "rel_id", "rel_type", "start_id", "end_id")
                },
            }

    rel_id = record.get("rel_id")
    if rel_id is not None:
        rkey = str(rel_id)
        if rkey not in relationships:
            relationships[rkey] = {
                "Relationship ID": rkey,
                "Type": record.get("rel_type", ""),
                "Properties": {},
                "Start Node ID": str(record.get("start_id", "")),
                "End Node ID": str(record.get("end_id", "")),
            }
