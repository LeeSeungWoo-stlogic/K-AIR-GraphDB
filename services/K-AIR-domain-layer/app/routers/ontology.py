"""K-AIR Domain Layer — 온톨로지 핵심 라우터 (AGE 기반)

robo-data-domain-layer의 ontology_schema, ontology_explorer, ontology_causal,
ontology_relationship 라우터를 K-AIR-GraphDB(AGE)로 전환한 통합 라우터.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_age_service, get_schema_store, get_age_conn

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 요청/응답 모델 ──

class SchemaCreateRequest(BaseModel):
    name: str
    description: str = ""
    domain: str = ""
    schema_json: Dict[str, Any] = {}


class NodeCreateRequest(BaseModel):
    schema_id: str
    label: str
    properties: Dict[str, Any] = {}


class RelationshipCreateRequest(BaseModel):
    schema_id: str
    source_id: str
    target_id: str
    rel_type: str
    properties: Dict[str, Any] = {}


class CausalQueryRequest(BaseModel):
    target_node_id: str
    max_depth: int = 5


# ── 스키마 CRUD ──

@router.get("/schemas", summary="온톨로지 스키마 목록 조회")
async def list_schemas():
    store = get_schema_store()
    schemas = await store.list_schemas()
    return {"success": True, "data": schemas}


@router.post("/schemas", summary="온톨로지 스키마 생성")
async def create_schema(req: SchemaCreateRequest):
    store = get_schema_store()
    result = await store.create_schema(
        name=req.name,
        description=req.description,
        domain=req.domain,
        schema_json=req.schema_json,
    )
    return {"success": True, "data": result}


@router.get("/schemas/{schema_id}", summary="스키마 상세 조회")
async def get_schema(schema_id: str):
    store = get_schema_store()
    schema = await store.get_schema(schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")
    return {"success": True, "data": schema}


# ── 노드 (ObjectType) CRUD ──

@router.get("/nodes", summary="온톨로지 노드 목록 조회")
async def list_nodes(
    schema_id: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
):
    svc = get_age_service()
    nodes = await svc.get_ontology_nodes(schema_id=schema_id, label=label)
    return {"success": True, "data": nodes}


@router.post("/nodes", summary="온톨로지 노드 생성")
async def create_node(req: NodeCreateRequest):
    svc = get_age_service()
    result = await svc.create_ontology_node(
        schema_id=req.schema_id,
        label=req.label,
        properties=req.properties,
    )
    return {"success": True, "data": result}


# ── 관계 CRUD ──

@router.get("/relationships", summary="온톨로지 관계 목록 조회")
async def list_relationships(schema_id: Optional[str] = Query(None)):
    svc = get_age_service()
    rels = await svc.get_ontology_relationships(schema_id=schema_id)
    return {"success": True, "data": rels}


@router.post("/relationships", summary="온톨로지 관계 생성")
async def create_relationship(req: RelationshipCreateRequest):
    svc = get_age_service()
    result = await svc.create_ontology_relationship(
        schema_id=req.schema_id,
        source_id=req.source_id,
        target_id=req.target_id,
        rel_type=req.rel_type,
        properties=req.properties,
    )
    return {"success": True, "data": result}


# ── 인과 분석 (Causal Analysis) ──

@router.post("/causal/trace", summary="KPI 인과 체인 역추적 (AGE 그래프 경로 탐색)")
async def causal_trace(req: CausalQueryRequest):
    """AGE의 가변 길이 경로 탐색으로 KPI 원인 체인을 추출한다.

    기존 robo-data-domain-layer의 ontology_causal.py가 Neo4j Cypher
    [*1..N] 패턴을 사용하던 것을 AGE Cypher로 동일하게 수행한다.
    """
    conn = get_age_conn()
    try:
        paths = await conn.execute_cypher(
            f"""
            MATCH path = (source)-[*1..{req.max_depth}]->(target {{id: '{req.target_node_id}'}})
            RETURN
                [n IN nodes(path) | {{id: n.id, name: n.name, label: label(n)}}] AS chain,
                [r IN relationships(path) | type(r)] AS relation_types,
                length(path) AS depth
            ORDER BY depth
            LIMIT 50
            """
        )
        chains = []
        for row in paths:
            chains.append({
                "chain": row[0] if len(row) > 0 else [],
                "relation_types": row[1] if len(row) > 1 else [],
                "depth": row[2] if len(row) > 2 else 0,
            })
        return {"success": True, "data": {"paths": chains, "count": len(chains)}}
    except Exception as e:
        logger.error("인과 분석 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"Causal trace failed: {e}")


# ── 탐색 (Explorer) ──

@router.get("/explorer/search", summary="온톨로지 노드 검색")
async def search_nodes(
    q: str = Query(..., description="검색 키워드"),
    label: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    svc = get_age_service()
    results = await svc.search_nodes(query=q, label=label, limit=limit)
    return {"success": True, "data": results}
