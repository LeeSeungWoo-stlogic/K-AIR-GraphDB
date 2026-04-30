"""카탈로그 추출기 팩토리.

실구현: postgres. oracle/mysql/tibero 는 골격(NotImplementedError) — 이기종 실DB·Mongo 등은
PM 별도 트랙에서 목업/스텁으로 확장 (docs/step1_completion_bundle/NON_POSTGRES_ADAPTERS_SCOPE.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import SourceConfig, source_engine
from .base import CatalogExtractor
from .postgres import PostgresCatalogExtractor

if TYPE_CHECKING:
    pass


def get_catalog_extractor(name: str | None = None) -> CatalogExtractor:
    key = (name or source_engine()).strip().lower()
    if key in ("postgres", "postgresql", "pg"):
        return PostgresCatalogExtractor()
    if key == "oracle":
        from .oracle import OracleCatalogExtractor

        return OracleCatalogExtractor()
    if key in ("mysql", "mariadb"):
        from .mysql import MySQLCatalogExtractor

        return MySQLCatalogExtractor()
    if key == "tibero":
        from .tibero import TiberoCatalogExtractor

        return TiberoCatalogExtractor()
    raise ValueError(f"Unknown SOURCE_ENGINE={key!r} (expected postgres|oracle|mysql|tibero)")


def extract_catalog(src: SourceConfig, db_label: str) -> dict[str, Any]:
    ext = get_catalog_extractor()
    return ext.extract(src, db_label)
