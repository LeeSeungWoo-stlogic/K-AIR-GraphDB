from __future__ import annotations

from typing import Any

from ..config import SourceConfig
from .base import CatalogExtractor


class TiberoCatalogExtractor(CatalogExtractor):
    """Oracle 호환 뷰 재사용 thin wrapper 스켈레톤. 실DB 추출·검증은 TODO."""

    source_engine = "tibero"

    def extract(self, src: SourceConfig, db_label: str) -> dict[str, Any]:
        raise NotImplementedError(
            "TiberoCatalogExtractor: Oracle 호환 메타뷰 기반 추출·드라이버 연동 TODO "
            "(계획안 골격 단계)"
        )
