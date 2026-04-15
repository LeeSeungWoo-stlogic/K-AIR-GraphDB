"""K-AIR Domain Layer 설정 — Neo4j 제거, K-AIR-GraphDB(PostgreSQL+AGE) 전용"""

from typing import Literal, Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphDBConfig(BaseModel):
    """K-AIR-GraphDB 연결 설정 (PostgreSQL + Apache AGE + pgvector)"""
    host: str = "localhost"
    port: int = 15432
    database: str = "kair_graphdb"
    user: str = "kair"
    password: str = "kair_pass"
    graph_name: str = "ontology_graph"
    min_pool: int = 2
    max_pool: int = 10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    port: int = 8002
    debug: bool = False

    llm_provider: Literal["openai", "google", "anthropic"] = "openai"
    llm_model: str = "gpt-4.1-2025-04-14"
    light_llm_provider: Literal["openai", "google", "anthropic"] = "openai"
    light_llm_model: str = "gpt-4.1-mini-2025-04-14"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    graphdb: GraphDBConfig = GraphDBConfig()

    text2sql_url: str = "http://127.0.0.1:8000"


settings = Settings()
