from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str
    schema: str


@dataclass(frozen=True)
class TargetConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def source_engine() -> str:
    return os.environ.get("SOURCE_ENGINE", "postgres").strip().lower()


def load_source() -> SourceConfig:
    return SourceConfig(
        host=_env("SOURCE_PG_HOST", "host.docker.internal"),
        port=int(_env("SOURCE_PG_PORT", "5432")),
        user=_env("SOURCE_PG_USER", "postgres"),
        password=_env("SOURCE_PG_PASSWORD", "postgres123"),
        dbname=_env("SOURCE_PG_DB", "rwis"),
        schema=_env("SOURCE_PG_SCHEMA", "RWIS"),
    )


def load_target() -> TargetConfig:
    return TargetConfig(
        host=_env("TARGET_PG_HOST", "host.docker.internal"),
        port=int(_env("TARGET_PG_PORT", "15433")),
        user=_env("TARGET_PG_USER", "kair"),
        password=_env("TARGET_PG_PASSWORD", "kair_pass"),
        dbname=_env("TARGET_PG_DB", "kair_graphdb_t2s"),
    )


def meta_db_label() -> str:
    return _env("META_DB_LABEL", "rwis_robo_postgres")


def age_graph_name() -> str:
    return os.environ.get("META_AGE_GRAPH_NAME", "ontology_graph")


def skip_age_physical() -> bool:
    return os.environ.get("META_INGEST_SKIP_AGE_PHYSICAL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def dsn_pg(cfg: SourceConfig | TargetConfig, db: str) -> str:
    return (
        f"host={cfg.host} port={cfg.port} dbname={db} "
        f"user={cfg.user} password={cfg.password} sslmode=disable"
    )
