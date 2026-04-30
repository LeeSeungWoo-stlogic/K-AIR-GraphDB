from __future__ import annotations

from typing import Any

from ..config import SourceConfig
from .base import CatalogExtractor


class MySQLCatalogExtractor(CatalogExtractor):
    """information_schema 기반 스켈레톤. 실DB 추출·검증은 TODO."""

    source_engine = "mysql"

    def extract(self, src: SourceConfig, db_label: str) -> dict[str, Any]:
        raise NotImplementedError(
            "MySQLCatalogExtractor: information_schema (TABLES, COLUMNS, "
            "KEY_COLUMN_USAGE …) 추출 연동 TODO (계획안 골격 단계)"
        )
