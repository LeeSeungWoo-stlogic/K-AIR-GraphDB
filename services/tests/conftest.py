"""E2E 통합 테스트 공통 fixture — K-AIR-GraphDB 연결"""

import asyncio
import pytest
import pytest_asyncio
import asyncpg

GRAPHDB_DSN = "postgresql://kair:kair_pass@localhost:15432/kair_graphdb"

pytest_plugins = ['pytest_asyncio']


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    pool = await asyncpg.create_pool(GRAPHDB_DSN, min_size=2, max_size=5)
    yield pool
    await pool.close()
