"""K-AIR Text2SQL — FastAPI 메인 애플리케이션

robo-data-text2sql의 Neo4j 의존성을 K-AIR-GraphDB(pgvector)로
전환한 서비스 래퍼.

원본: repos/KAIR/robo-data-text2sql/app/main.py
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import init_graphdb, init_target_db, close_all, get_pg_t2s_conn

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("K-AIR Text2SQL API 시작...")

    try:
        await init_graphdb()
        app.state.graphdb_connected = True
        logger.info("K-AIR-GraphDB(text2sql) 연결 성공")
    except Exception as e:
        logger.warning("K-AIR-GraphDB 연결 실패: %s", e)
        app.state.graphdb_connected = False

    try:
        await init_target_db()
        logger.info("대상 DB 연결 성공")
    except Exception as e:
        logger.warning("대상 DB 연결 실패 (무시): %s", e)

    yield

    await close_all()
    logger.info("K-AIR Text2SQL API 종료")


app = FastAPI(
    title="K-AIR Text2SQL API",
    description="자연어 → SQL 변환 서비스 (K-AIR-GraphDB pgvector 기반 RAG)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import text2sql
app.include_router(text2sql.router, prefix="/v1/text2sql", tags=["Text2SQL"])


@app.get("/health")
async def health_check():
    graphdb = "connected" if getattr(app.state, "graphdb_connected", False) else "disconnected"
    return {
        "status": "healthy",
        "service": "K-AIR-text2sql",
        "graphdb": graphdb,
        "backend": "K-AIR-GraphDB (PostgreSQL + pgvector)",
        "config": {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "embedding": f"{settings.embedding_provider}:{settings.embedding_model}",
        },
    }


@app.get("/")
async def root():
    return {
        "service": "K-AIR Text2SQL API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)
