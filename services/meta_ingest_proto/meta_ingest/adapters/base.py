from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..config import SourceConfig


class CatalogExtractor(ABC):
    """원천 DB → 카탈로그 dict (스냅샷)."""

    source_engine: str

    @abstractmethod
    def extract(self, src: SourceConfig, db_label: str) -> dict[str, Any]:
        raise NotImplementedError
