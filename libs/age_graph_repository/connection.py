"""
Apache AGE 비동기 연결 관리.

Neo4j AsyncGraphDatabase.driver()를 대체하는 asyncpg 기반 연결 풀.
모든 AGE Cypher는 SELECT * FROM cypher('graph', $$ ... $$) SQL 래핑이 필요하므로,
이 모듈에서 래핑·세션 관리를 캡슐화한다.
"""

from __future__ import annotations

import asyncpg
from typing import Any, Optional


class AgeConnection:
    """Apache AGE PostgreSQL 비동기 연결 관리자.

    사용법::

        conn = AgeConnection(host="localhost", port=15432,
                             database="kair_graphdb", user="kair", password="kair_pass")
        await conn.connect()
        rows = await conn.execute_cypher("MATCH (n) RETURN count(n)")
        await conn.close()

    async with 지원::

        async with AgeConnection(...) as conn:
            rows = await conn.execute_cypher("MATCH (n:KPI) RETURN n.name")
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 15432,
        database: str = "kair_graphdb",
        user: str = "kair",
        password: str = "kair_pass",
        graph_name: str = "ontology_graph",
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.graph_name = graph_name
        self._min_pool = min_pool_size
        self._max_pool = max_pool_size
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
            min_size=self._min_pool,
            max_size=self._max_pool,
            setup=self._setup_connection,
        )

    @staticmethod
    async def _setup_connection(conn: asyncpg.Connection) -> None:
        """매 커넥션 생성 시 AGE 확장 로드 + search_path 설정."""
        await conn.execute("LOAD 'age';")
        await conn.execute("SET search_path = ag_catalog, \"$user\", public;")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> "AgeConnection":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Not connected. Call connect() or use 'async with'.")
        return self._pool

    async def verify_connection(self) -> bool:
        """연결 및 AGE 확장 정상 여부 확인."""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchval(
                    f"SELECT * FROM cypher('{self.graph_name}', "
                    "$$ RETURN 1 $$) AS (r agtype);"
                )
                return row is not None
        except Exception:
            return False

    async def execute_cypher(
        self,
        cypher: str,
        *,
        return_cols: str = "(r agtype)",
        graph: Optional[str] = None,
    ) -> list[asyncpg.Record]:
        """AGE Cypher를 실행하고 결과 행을 반환한다.

        Args:
            cypher: Cypher 쿼리 문자열 (SELECT 래핑 없이 순수 Cypher).
            return_cols: AS 절의 컬럼 정의. 기본 ``(r agtype)``.
            graph: 그래프 이름. 기본값은 생성자에서 지정한 ``graph_name``.

        Returns:
            asyncpg.Record 리스트.
        """
        g = graph or self.graph_name
        sql = (
            f"SELECT * FROM cypher('{g}', $$ {cypher} $$) "
            f"AS {return_cols};"
        )
        async with self.pool.acquire() as conn:
            return await conn.fetch(sql)

    async def execute_cypher_scalar(
        self,
        cypher: str,
        *,
        graph: Optional[str] = None,
    ) -> Any:
        """단일 값(스칼라)을 반환하는 Cypher 실행."""
        g = graph or self.graph_name
        sql = (
            f"SELECT * FROM cypher('{g}', $$ {cypher} $$) "
            f"AS (r agtype);"
        )
        async with self.pool.acquire() as conn:
            return await conn.fetchval(sql)

    async def execute_sql(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        """일반 SQL 실행 (pgvector 검색, RDB 테이블 등)."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def execute_sql_status(self, sql: str, *args: Any) -> str:
        """SQL 실행 후 상태 문자열 반환 (INSERT/DELETE 등)."""
        async with self.pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def ensure_vlabel(self, label: str) -> None:
        """Vertex label이 없으면 생성."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"SELECT * FROM ag_catalog.create_vlabel("
                    f"'{self.graph_name}', '{label}');"
                )
        except (asyncpg.exceptions.DuplicateTableError,
                asyncpg.exceptions.InvalidSchemaNameError):
            pass

    async def ensure_elabel(self, label: str) -> None:
        """Edge label이 없으면 생성."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"SELECT * FROM ag_catalog.create_elabel("
                    f"'{self.graph_name}', '{label}');"
                )
        except (asyncpg.exceptions.DuplicateTableError,
                asyncpg.exceptions.InvalidSchemaNameError):
            pass
