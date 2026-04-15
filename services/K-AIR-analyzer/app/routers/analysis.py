"""K-AIR Analyzer — 분석 라우터 (PostgreSQL 기반)

robo-data-analyzer의 analysis_router를 K-AIR-GraphDB로 전환.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.deps import (
    get_graph_query_service,
    get_schema_manage_service,
    get_related_tables_service,
    get_lineage_service,
    get_metadata_service,
    get_phase_ddl,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 그래프 데이터 조회 ──

@router.get("/graph/exists", summary="분석 그래프 데이터 존재 여부 확인")
async def check_graph_exists():
    svc = get_graph_query_service()
    exists = await svc.check_graph_data_exists()
    return {"success": True, "exists": exists}


@router.get("/graph/data", summary="전체 그래프 데이터 조회")
async def fetch_graph_data():
    svc = get_graph_query_service()
    data = await svc.fetch_graph_data()
    return {"success": True, "data": data}


@router.delete("/graph/data", summary="그래프 데이터 삭제")
async def cleanup_graph():
    svc = get_graph_query_service()
    await svc.cleanup_graph()
    return {"success": True, "message": "Graph data cleaned up"}


# ── 스키마/테이블 관리 ──

@router.get("/schema/tables", summary="테이블 목록 조회 (시맨틱 검색 지원)")
async def list_tables(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    svc = get_schema_manage_service()
    tables = await svc.fetch_schema_tables(search=search, limit=limit)
    return {"success": True, "data": tables}


@router.get("/schema/tables/{table_name}/columns", summary="테이블 컬럼 조회")
async def get_table_columns(table_name: str):
    svc = get_schema_manage_service()
    columns = await svc.fetch_table_columns(table_name)
    return {"success": True, "data": columns}


# ── 관련 테이블 조회 ──

class RelatedTablesRequest(BaseModel):
    mode: str = "ROBO"
    tableName: str
    schemaName: str = "public"


@router.post("/related-tables", summary="관련 테이블 조회 (ROBO/TEXT2SQL)")
async def fetch_related_tables(req: RelatedTablesRequest):
    svc = get_related_tables_service()
    result = await svc.fetch_related_tables_unified(req.model_dump())
    return {"success": True, "data": result}


# ── 리니지 ──

@router.get("/lineage", summary="데이터 리니지 그래프 조회")
async def fetch_lineage():
    svc = get_lineage_service()
    graph = await svc.fetch_lineage_graph()
    return {"success": True, "data": graph}


class SaveLineageRequest(BaseModel):
    process_name: str
    source_tables: List[str]
    target_tables: List[str]
    properties: Dict[str, Any] = {}


@router.post("/lineage", summary="리니지 저장")
async def save_lineage(req: SaveLineageRequest):
    svc = get_lineage_service()
    result = await svc.save_lineage(
        process_name=req.process_name,
        source_tables=req.source_tables,
        target_tables=req.target_tables,
        properties=req.properties,
    )
    return {"success": True, "data": result}


# ── 메타데이터 보강 ──

@router.get("/metadata/tables-without-description", summary="설명 없는 테이블 목록")
async def tables_without_description():
    svc = get_metadata_service()
    tables = await svc.get_tables_without_description()
    return {"success": True, "data": tables}
