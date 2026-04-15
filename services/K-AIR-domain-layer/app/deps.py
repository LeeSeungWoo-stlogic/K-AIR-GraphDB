"""K-AIR Domain Layer 의존성 주입 — K-AIR-GraphDB(AGE) 기반

기존 robo-data-domain-layer의 Neo4jService + SchemaStore를
AgeConnection + AgeService + AgeSchemaStore로 교체한다.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from age_graph_repository import AgeConnection
from age_graph_repository.services import AgeService, AgeSchemaStore

from app.config import settings

logger = logging.getLogger(__name__)

_age_conn: Optional[AgeConnection] = None
_age_service: Optional[AgeService] = None
_schema_store: Optional[AgeSchemaStore] = None
_pg_pool: Optional[asyncpg.Pool] = None


async def init_graphdb() -> None:
    """K-AIR-GraphDB 연결 초기화 (lifespan startup에서 호출)"""
    global _age_conn, _age_service, _schema_store, _pg_pool

    cfg = settings.graphdb

    _age_conn = AgeConnection(
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        user=cfg.user,
        password=cfg.password,
        graph_name=cfg.graph_name,
    )
    await _age_conn.connect()

    _age_service = AgeService(_age_conn)
    connected = await _age_service.verify_connection()
    logger.info("K-AIR-GraphDB(AGE) 연결 %s", "성공" if connected else "실패")

    _schema_store = AgeSchemaStore()
    _schema_store.set_age_service(_age_service)

    _pg_pool = await asyncpg.create_pool(
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        user=cfg.user,
        password=cfg.password,
        min_size=cfg.min_pool,
        max_size=cfg.max_pool,
    )
    logger.info("K-AIR-GraphDB asyncpg 풀 생성 완료 (min=%d, max=%d)", cfg.min_pool, cfg.max_pool)


async def close_graphdb() -> None:
    """K-AIR-GraphDB 연결 종료 (lifespan shutdown에서 호출)"""
    global _age_conn, _age_service, _schema_store, _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
    if _age_conn:
        await _age_conn.close()
        _age_conn = None
    _age_service = None
    _schema_store = None
    logger.info("K-AIR-GraphDB 연결 종료")


def get_age_service() -> AgeService:
    if _age_service is None:
        raise RuntimeError("AgeService not initialized")
    return _age_service


def get_schema_store() -> AgeSchemaStore:
    if _schema_store is None:
        raise RuntimeError("AgeSchemaStore not initialized")
    return _schema_store


def get_age_conn() -> AgeConnection:
    if _age_conn is None:
        raise RuntimeError("AgeConnection not initialized")
    return _age_conn


def get_pg_pool() -> asyncpg.Pool:
    if _pg_pool is None:
        raise RuntimeError("PG Pool not initialized")
    return _pg_pool
