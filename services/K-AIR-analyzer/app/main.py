"""K-AIR Analyzer — FastAPI 메인 애플리케이션

robo-data-analyzer의 Neo4j 의존성을 K-AIR-GraphDB(PostgreSQL)로
전환한 서비스 래퍼.

원본: repos/KAIR/robo-data-analyzer/main.py
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import init_graphdb, close_graphdb

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("K-AIR Analyzer 시작 — port=%d", settings.port)

    try:
        await init_graphdb()
        app.state.graphdb_connected = True
    except Exception as e:
        logger.warning("K-AIR-GraphDB 연결 실패: %s", e)
        app.state.graphdb_connected = False

    yield

    await close_graphdb()
    logger.info("K-AIR Analyzer 종료")


app = FastAPI(
    title="K-AIR Analyzer",
    description="소스 코드 분석 및 메타데이터 관리 서비스 (K-AIR-GraphDB 기반)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import analysis, glossary
app.include_router(analysis.router, prefix="/v1/analyzer", tags=["Analysis"])
app.include_router(glossary.router, prefix="/v1/analyzer", tags=["Glossary & Calendar"])


@app.get("/")
async def root():
    return {"status": "ok", "service": "K-AIR-analyzer", "version": "2.0.0"}


@app.get("/health")
async def health():
    graphdb = "connected" if getattr(app.state, "graphdb_connected", False) else "disconnected"
    return {
        "status": "healthy",
        "service": "K-AIR-analyzer",
        "graphdb": graphdb,
        "backend": "K-AIR-GraphDB (PostgreSQL + asyncpg)",
        "config": {
            "file_concurrency": settings.concurrency.file_concurrency,
            "max_concurrency": settings.concurrency.max_concurrency,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
