"""K-AIR Analyzer 설정 — Neo4j 제거, K-AIR-GraphDB(PostgreSQL) 전용"""

import os
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphDBConfig(BaseModel):
    """K-AIR-GraphDB 연결 설정"""
    host: str = "localhost"
    port: int = 15432
    database: str = "kair_graphdb"
    user: str = "kair"
    password: str = "kair_pass"
    min_pool: int = 2
    max_pool: int = 10


class LLMConfig(BaseModel):
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4.1"
    max_tokens: int = 32768


class ConcurrencyConfig(BaseModel):
    file_concurrency: int = 5
    max_concurrency: int = 5


class BatchConfig(BaseModel):
    max_batch_token: int = 1000
    query_batch_size: int = 30


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 5502

    graphdb: GraphDBConfig = GraphDBConfig()
    llm: LLMConfig = LLMConfig()
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    batch: BatchConfig = BatchConfig()

    metadata_text2sql_api_url: str = ""
    fk_inference_enabled: bool = True


settings = Settings()
