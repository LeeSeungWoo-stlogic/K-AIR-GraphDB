"""K-AIR Analyzer 의존성 주입 — K-AIR-GraphDB(asyncpg) 기반

기존 robo-data-analyzer의 Neo4jClient를 PgAnalyzerClient로 교체.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from age_graph_repository.analyzer import (
    PgAnalyzerClient,
    PgGraphQueryService,
    PgGlossaryService,
    PgSchemaManageService,
    PgRelatedTablesService,
    PgLineageService,
    PgMetadataService,
    PgBusinessCalendarService,
    PgPhaseDDL,
)

from app.config import settings

logger = logging.getLogger(__name__)

_pg_pool: Optional[asyncpg.Pool] = None
_pg_client: Optional[PgAnalyzerClient] = None


async def init_graphdb() -> None:
    """K-AIR-GraphDB analyzer 연결 초기화"""
    global _pg_pool, _pg_client
    cfg = settings.graphdb
    _pg_pool = await asyncpg.create_pool(
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        user=cfg.user,
        password=cfg.password,
        min_size=cfg.min_pool,
        max_size=cfg.max_pool,
    )
    _pg_client = PgAnalyzerClient(_pg_pool, batch_size=settings.batch.query_batch_size)
    logger.info("K-AIR-GraphDB(analyzer) 연결 성공")


async def close_graphdb() -> None:
    """연결 종료"""
    global _pg_pool, _pg_client
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
    _pg_client = None
    logger.info("K-AIR-GraphDB(analyzer) 연결 종료")


def get_pg_pool() -> asyncpg.Pool:
    if _pg_pool is None:
        raise RuntimeError("PG Pool not initialized")
    return _pg_pool


def get_pg_client() -> PgAnalyzerClient:
    if _pg_client is None:
        raise RuntimeError("PgAnalyzerClient not initialized")
    return _pg_client


def get_graph_query_service() -> PgGraphQueryService:
    return PgGraphQueryService(get_pg_pool())


def get_glossary_service() -> PgGlossaryService:
    return PgGlossaryService(get_pg_pool())


def get_schema_manage_service() -> PgSchemaManageService:
    return PgSchemaManageService(get_pg_pool())


def get_related_tables_service() -> PgRelatedTablesService:
    return PgRelatedTablesService(get_pg_pool())


def get_lineage_service() -> PgLineageService:
    return PgLineageService(get_pg_pool())


def get_metadata_service() -> PgMetadataService:
    return PgMetadataService(get_pg_pool())


def get_business_calendar_service() -> PgBusinessCalendarService:
    return PgBusinessCalendarService(get_pg_pool())


def get_phase_ddl() -> PgPhaseDDL:
    return PgPhaseDDL(get_pg_pool())
