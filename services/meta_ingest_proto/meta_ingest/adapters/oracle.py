from __future__ import annotations

from typing import Any

from ..config import SourceConfig
from .base import CatalogExtractor


class OracleCatalogExtractor(CatalogExtractor):
    """Oracle ALL_* 카탈로그 스켈레톤. 실DB 추출·검증은 TODO."""

    source_engine = "oracle"

    def extract(self, src: SourceConfig, db_label: str) -> dict[str, Any]:
        raise NotImplementedError(
            "OracleCatalogExtractor: ALL_TABLES / ALL_TAB_COLUMNS / ALL_CONSTRAINTS 등 "
            "스키마별 추출 SQL 연동 TODO (계획안 골격 단계)"
        )
