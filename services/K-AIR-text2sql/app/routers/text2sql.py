"""K-AIR Text2SQL — 핵심 라우터 (pgvector 기반)

robo-data-text2sql의 ask, meta, history 라우터를 K-AIR-GraphDB(pgvector)로
전환한 통합 라우터.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_pg_t2s_conn

logger = logging.getLogger(__name__)
router = APIRouter()


class AskRequest(BaseModel):
    question: str
    schema_name: Optional[str] = None
    max_tables: int = 10


class TableSearchRequest(BaseModel):
    query: str
    top_k: int = 10


# ── 테이블 메타데이터 조회 ──

@router.get("/tables", summary="등록된 테이블 목록 조회")
async def list_tables(
    schema_name: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = get_pg_t2s_conn()
    query = "SELECT id, fqn, name, description FROM t2s_tables"
    params = []
    if schema_name:
        query += " WHERE schema_name = $1"
        params.append(schema_name)
    query += f" ORDER BY name LIMIT {limit}"
    rows = await conn.fetch(query, *params)
    return {"success": True, "data": [dict(r) for r in rows], "count": len(rows)}


@router.get("/tables/{table_name}/columns", summary="테이블 컬럼 조회")
async def get_columns(table_name: str):
    conn = get_pg_t2s_conn()
    rows = await conn.fetch(
        """SELECT c.id, c.name, c.data_type, c.description, c.is_pk, c.is_fk
           FROM t2s_columns c
           JOIN t2s_tables t ON c.table_id = t.id
           WHERE t.name = $1
           ORDER BY c.ordinal""",
        table_name,
    )
    return {"success": True, "data": [dict(r) for r in rows]}


# ── 벡터 검색 (테이블/컬럼 시맨틱 매칭) ──

@router.post("/search/tables", summary="테이블 시맨틱 검색 (pgvector)")
async def search_tables_vector(req: TableSearchRequest):
    """pgvector HNSW 인덱스를 사용한 테이블 벡터 검색.

    기존 Neo4j의 db.index.vector.queryNodes를 대체한다.
    """
    conn = get_pg_t2s_conn()
    try:
        from age_graph_repository.text2sql import pg_search_tables_text2sql_vector
        results = await pg_search_tables_text2sql_vector(
            pg_conn=conn,
            query_text=req.query,
            top_k=req.top_k,
        )
        return {"success": True, "data": results}
    except Exception as e:
        logger.error("테이블 벡터 검색 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── FK 관계 조회 ──

@router.get("/relationships/fk", summary="FK 관계 목록 조회")
async def list_fk_relationships(
    table_name: Optional[str] = Query(None),
):
    conn = get_pg_t2s_conn()
    if table_name:
        rows = await conn.fetch(
            """SELECT fc.id, fc.from_fqn, fc.to_fqn, fc.fk_columns, fc.confidence
               FROM t2s_fk_constraints fc
               WHERE fc.from_fqn LIKE $1 OR fc.to_fqn LIKE $1
               ORDER BY fc.confidence DESC""",
            f"%{table_name}%",
        )
    else:
        rows = await conn.fetch(
            "SELECT id, from_fqn, to_fqn, fk_columns, confidence FROM t2s_fk_constraints ORDER BY id LIMIT 200"
        )
    return {"success": True, "data": [dict(r) for r in rows]}


# ── 쿼리 이력 ──

@router.get("/history", summary="쿼리 이력 조회")
async def list_query_history(limit: int = Query(20, ge=1, le=100)):
    conn = get_pg_t2s_conn()
    rows = await conn.fetch(
        """SELECT id, natural_query, generated_sql, is_valid, created_at
           FROM t2s_queries
           ORDER BY created_at DESC
           LIMIT $1""",
        limit,
    )
    return {"success": True, "data": [dict(r) for r in rows]}
