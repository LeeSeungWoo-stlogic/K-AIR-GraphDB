"""K-AIR Text2SQL 설정 — Neo4j 제거, K-AIR-GraphDB(PostgreSQL+pgvector) 전용"""

from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class GraphDBConfig(BaseModel):
    """K-AIR-GraphDB 연결 설정"""
    host: str = "localhost"
    port: int = 15432
    database: str = "kair_graphdb"
    user: str = "kair"
    password: str = "kair_pass"
    min_pool: int = 2
    max_pool: int = 10


class TargetDBConfig(BaseModel):
    """분석 대상 DB 연결 설정"""
    type: str = "postgresql"
    host: str = "localhost"
    port: int = 5432
    name: str = "target_db"
    user: str = "postgres"
    password: str = "postgres"
    schema: str = "public"
    ssl: str = "disable"


class Settings(BaseSettings):
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    llm_provider: Literal["openai", "google", "openai_compatible"] = "openai"
    llm_model: str = "gpt-4.1-2025-04-14"
    light_llm_provider: Literal["openai", "google", "openai_compatible"] = "openai"
    light_llm_model: str = "gpt-4.1-mini-2025-04-14"

    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    openai_api_key: str = ""
    google_api_key: str = ""

    vector_top_k: int = 10
    max_fk_hops: int = 3

    sql_timeout_seconds: int = 30
    sql_row_limit: int = 1000

    graphdb: GraphDBConfig = GraphDBConfig()
    target_db: TargetDBConfig = TargetDBConfig()

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
