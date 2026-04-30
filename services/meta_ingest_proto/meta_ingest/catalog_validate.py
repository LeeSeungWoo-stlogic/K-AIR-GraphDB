"""카탈로그 추출 직후 정합성 검증 (보안: 비밀 필드 거부)."""

from __future__ import annotations

import re
from typing import Any

# Option B: 논리 라벨 전용 (엔진 코드는 넣지 않음)
_META_DB_LABEL_RE = re.compile(r"^[a-z0-9_]+$")

_FORBIDDEN_SOURCE_KEYS = frozenset(
    k.lower()
    for k in ("password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "user", "username", "userid")
)


def strip_secrets_from_source(catalog: dict[str, Any]) -> None:
    """로드된 JSON 등에서 source 블록의 식별자·비밀 필드를 제거(제자리)."""
    src = catalog.get("source")
    if not isinstance(src, dict):
        return
    for k in list(src.keys()):
        if k.lower() in _FORBIDDEN_SOURCE_KEYS:
            del src[k]


def validate_catalog_for_ingest(catalog: dict[str, Any]) -> None:
    """인제스트 직전 카탈로그 검증. 실패 시 ValueError."""
    label = catalog.get("meta_db_label")
    if not label or not isinstance(label, str):
        raise ValueError("catalog.meta_db_label must be a non-empty string")
    if not _META_DB_LABEL_RE.match(label):
        raise ValueError(
            f"catalog.meta_db_label must match {_META_DB_LABEL_RE.pattern!r} (Option B: no engine in label)"
        )
    schema = catalog.get("schema")
    if not schema or not isinstance(schema, str):
        raise ValueError("catalog.schema must be a non-empty string")
    if not catalog.get("source_engine"):
        raise ValueError("catalog.source_engine is required")
    tables = catalog.get("tables")
    if not isinstance(tables, list) or len(tables) == 0:
        raise ValueError("catalog.tables must be a non-empty list")
    src = catalog.get("source")
    if src is not None:
        if not isinstance(src, dict):
            raise ValueError("catalog.source must be an object or omitted")
        bad = sorted(k for k in src if k.lower() in _FORBIDDEN_SOURCE_KEYS)
        if bad:
            raise ValueError(f"catalog.source must not contain secrets or user ids, forbidden keys: {bad!r}")
