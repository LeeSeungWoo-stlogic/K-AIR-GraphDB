"""
text2sql용 asyncpg 연결 관리자 — Neo4jConnection drop-in 대체.

Neo4j Bolt 드라이버 대신 asyncpg 커넥션 풀을 사용하여
t2s_tables/columns/queries 등 RDB 테이블 + pgvector 검색을 수행한다.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import asyncpg

logger = logging.getLogger(__name__)


class PgConnection:
    """asyncpg 커넥션 풀 래퍼 — text2sql 그래프 데이터용.

    ``Neo4jConnection`` 과 유사한 라이프사이클 API를 제공:
      - connect() / close()
      - acquire() — 세션 대용으로 asyncpg.Connection 획득
      - execute() / fetch() — 편의 헬퍼
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        host: str = "localhost",
        port: int = 15432,
        database: str = "age_graph",
        user: str = "postgres",
        password: str = "postgres",
        min_size: int = 2,
        max_size: int = 10,
    ):
        self._dsn = dsn
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._min_size = min_size
        self._max_size = max_size
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        if self._dsn:
            self.pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        else:
            self.pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._user,
                password=self._password,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        logger.info(
            "PgConnection pool created (min=%d, max=%d) %s:%s/%s",
            self._min_size, self._max_size,
            self._host, self._port, self._database,
        )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("PgConnection pool closed")

    def acquire(self):
        """asyncpg 커넥션 컨텍스트 매니저.

        Usage::
            async with pg_conn.acquire() as conn:
                rows = await conn.fetch("SELECT ...")
        """
        if self.pool is None:
            raise RuntimeError("PgConnection pool is not initialized. Call connect() first.")
        return self.pool.acquire()

    async def fetch(self, sql: str, *args: Any) -> List[asyncpg.Record]:
        async with self.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> Optional[asyncpg.Record]:
        async with self.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        async with self.acquire() as conn:
            return await conn.fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any) -> str:
        async with self.acquire() as conn:
            return await conn.execute(sql, *args)
