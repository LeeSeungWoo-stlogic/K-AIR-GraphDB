"""K-AIR Text2SQL 의존성 주입 — K-AIR-GraphDB(pgvector) 기반

기존 robo-data-text2sql의 Neo4jConnection을 PgConnection으로 교체.
"""

from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from age_graph_repository.text2sql import PgConnection

from app.config import settings

logger = logging.getLogger(__name__)

_pg_t2s_conn: Optional[PgConnection] = None
_target_db_pool: Optional[asyncpg.Pool] = None


async def init_graphdb() -> None:
    """K-AIR-GraphDB text2sql 연결 초기화"""
    global _pg_t2s_conn
    cfg = settings.graphdb
    _pg_t2s_conn = PgConnection(
        host=cfg.host,
        port=cfg.port,
        database=cfg.database,
        user=cfg.user,
        password=cfg.password,
        min_size=cfg.min_pool,
        max_size=cfg.max_pool,
    )
    await _pg_t2s_conn.connect()
    logger.info("K-AIR-GraphDB(text2sql) 연결 성공")


async def init_target_db() -> None:
    """대상 DB 커넥션 풀 초기화"""
    global _target_db_pool
    cfg = settings.target_db
    if cfg.type in ("mysql", "mariadb"):
        logger.info("MySQL/MariaDB 모드: asyncpg 풀 생성 스킵")
        return
    ssl = cfg.ssl if cfg.ssl != "disable" else False
    _target_db_pool = await asyncpg.create_pool(
        host=cfg.host,
        port=cfg.port,
        database=cfg.name,
        user=cfg.user,
        password=cfg.password,
        ssl=ssl,
        min_size=2,
        max_size=10,
    )
    logger.info("대상 DB 커넥션 풀 생성 완료")


async def close_all() -> None:
    """모든 연결 종료"""
    global _pg_t2s_conn, _target_db_pool
    if _target_db_pool:
        await _target_db_pool.close()
        _target_db_pool = None
    if _pg_t2s_conn:
        await _pg_t2s_conn.close()
        _pg_t2s_conn = None
    logger.info("모든 DB 연결 종료")


def get_pg_t2s_conn() -> PgConnection:
    if _pg_t2s_conn is None:
        raise RuntimeError("PgConnection(text2sql) not initialized")
    return _pg_t2s_conn


def get_target_db_pool() -> asyncpg.Pool:
    if _target_db_pool is None:
        raise RuntimeError("Target DB pool not initialized")
    return _target_db_pool
