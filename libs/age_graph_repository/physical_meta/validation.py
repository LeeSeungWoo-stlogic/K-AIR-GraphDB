from __future__ import annotations

from typing import Any

from .models import frozen_column_keys, frozen_fk_to_keys, frozen_table_keys


def validate_age_table_props(props: dict[str, Any]) -> None:
    ks = frozenset(props.keys())
    allowed = frozen_table_keys()
    if ks != allowed:
        missing = sorted(allowed - ks)
        extra = sorted(ks - allowed)
        raise ValueError(f"Table props key mismatch: missing={missing!r} extra={extra!r}")


def validate_age_column_props(props: dict[str, Any]) -> None:
    ks = frozenset(props.keys())
    allowed = frozen_column_keys()
    if ks != allowed:
        missing = sorted(allowed - ks)
        extra = sorted(ks - allowed)
        raise ValueError(f"Column props key mismatch: missing={missing!r} extra={extra!r}")


def validate_age_fk_props(props: dict[str, Any]) -> None:
    ks = frozenset(props.keys())
    allowed = frozen_fk_to_keys()
    if ks != allowed:
        missing = sorted(allowed - ks)
        extra = sorted(ks - allowed)
        raise ValueError(f"FK_TO props key mismatch: missing={missing!r} extra={extra!r}")


def validate_has_column_empty(props: dict[str, Any]) -> None:
    if props:
        raise ValueError(f"HAS_COLUMN must have empty props, got keys={sorted(props)!r}")
