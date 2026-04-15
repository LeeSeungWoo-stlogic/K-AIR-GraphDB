"""K-AIR Domain Layer — FastAPI 메인 애플리케이션

robo-data-domain-layer의 Neo4j 의존성을 K-AIR-GraphDB(AGE+pgvector)로
전환한 서비스 래퍼. 동일한 API 구조를 유지하면서 백엔드만 교체한다.

원본: repos/KAIR/robo-data-domain-layer/app/main.py
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.deps import init_graphdb, close_graphdb, get_age_service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("K-AIR Domain Layer 시작 — port=%s", settings.port)

    try:
        await init_graphdb()
        svc = get_age_service()
        ok = await svc.verify_connection()
        app.state.graphdb_connected = ok
        logger.info("K-AIR-GraphDB(AGE) 연결 %s", "성공" if ok else "실패")
    except Exception as e:
        logger.warning("K-AIR-GraphDB 연결 실패: %s", e)
        app.state.graphdb_connected = False

    yield

    await close_graphdb()
    logger.info("K-AIR Domain Layer 종료")


app = FastAPI(
    title="K-AIR Domain Layer API",
    description="도메인 온톨로지 스키마 생성 및 관리 서비스 (K-AIR-GraphDB 기반)",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import ontology
app.include_router(ontology.router, prefix="/v1/ontology", tags=["Ontology"])


@app.get("/health")
async def health_check():
    graphdb = "connected" if getattr(app.state, "graphdb_connected", False) else "disconnected"
    return {
        "status": "healthy",
        "service": "K-AIR-domain-layer",
        "graphdb": graphdb,
        "backend": "K-AIR-GraphDB (PostgreSQL + Apache AGE + pgvector)",
    }


@app.get("/")
async def root():
    return {
        "service": "K-AIR Domain Layer API",
        "version": "2.0.0",
        "description": "도메인 온톨로지 스키마 생성 및 관리 서비스 (K-AIR-GraphDB 기반)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=settings.debug)
