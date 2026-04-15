"""K-AIR Analyzer — 용어 사전 라우터 (PostgreSQL 기반)

robo-data-analyzer의 glossary_router를 K-AIR-GraphDB로 전환.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_glossary_service, get_business_calendar_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 용어 사전 CRUD ──

@router.get("/glossaries", summary="용어 사전 목록 조회")
async def list_glossaries():
    svc = get_glossary_service()
    data = await svc.fetch_all_glossaries()
    return {"success": True, "data": data}


class CreateGlossaryRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "General"


@router.post("/glossaries", summary="용어 사전 생성")
async def create_glossary(req: CreateGlossaryRequest):
    svc = get_glossary_service()
    result = await svc.create_glossary(req.name, req.description, req.category)
    return {"success": True, "data": result}


# ── 용어 CRUD ──

@router.get("/glossaries/{glossary_id}/terms", summary="용어 목록 조회")
async def list_terms(glossary_id: int):
    svc = get_glossary_service()
    terms = await svc.fetch_terms(glossary_id)
    return {"success": True, "data": terms}


class CreateTermRequest(BaseModel):
    name: str
    definition: str = ""
    synonyms: str = ""


@router.post("/glossaries/{glossary_id}/terms", summary="용어 생성")
async def create_term(glossary_id: int, req: CreateTermRequest):
    svc = get_glossary_service()
    result = await svc.create_term(glossary_id, req.name, req.definition, req.synonyms)
    return {"success": True, "data": result}


# ── 영업일 달력 ──

@router.get("/calendars", summary="영업일 달력 목록 조회")
async def list_calendars():
    svc = get_business_calendar_service()
    data = await svc.fetch_all_calendars()
    return {"success": True, "data": data}


class CreateCalendarRequest(BaseModel):
    name: str
    year: int
    description: str = ""


@router.post("/calendars", summary="영업일 달력 생성")
async def create_calendar(req: CreateCalendarRequest):
    svc = get_business_calendar_service()
    result = await svc.create_calendar(req.name, req.year, req.description)
    return {"success": True, "data": result}
