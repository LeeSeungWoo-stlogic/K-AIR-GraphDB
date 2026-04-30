from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


def table_vertex_eid(db_label: str, schema: str, table_name: str) -> str:
    return f"meta_ingest:T:{db_label}:{schema}:{table_name}"


def column_vertex_eid(db_label: str, schema: str, table_name: str, column: str) -> str:
    return f"meta_ingest:C:{db_label}:{schema}:{table_name}:{column}"


def database_vertex_eid(db_label: str) -> str:
    return f"meta_ingest:D:{db_label}"


@dataclass
class DatabasePhysicalProps:
    """논리 데이터소스(:Database) — meta_db_label(Option B) + source_engine."""

    meta_db_label: str
    source_engine: str
    _meta_ingest: bool
    _physical_vertex_id: str

    def to_age_property_map(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


@dataclass
class TablePhysicalProps:
    """:Table 물리 본문 + 운영 확장(_meta_ingest, _physical_vertex_id)."""

    name: str
    schema: str
    description: str
    analyzed_description: str
    table_type: str
    db_exists: bool
    datasource: str
    _meta_ingest: bool
    _physical_vertex_id: str

    def to_age_property_map(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


@dataclass
class ColumnPhysicalProps:
    """:Column 물리 본문 + 운영 확장."""

    name: str
    fqn: str
    dtype: str
    nullable: bool
    is_primary_key: bool
    description: str
    ordinal_position: int
    column_default: str
    is_unique: bool
    _meta_ingest: bool
    _physical_vertex_id: str

    def to_age_property_map(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


@dataclass
class FkToEdgeProps:
    """(:Column)-[:FK_TO]->(:Column) 물리 속성."""

    constraint: str
    position: int

    def to_age_property_map(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


def frozen_table_keys() -> frozenset[str]:
    return frozenset(f.name for f in fields(TablePhysicalProps))


def frozen_database_keys() -> frozenset[str]:
    return frozenset(f.name for f in fields(DatabasePhysicalProps))


def frozen_column_keys() -> frozenset[str]:
    return frozenset(f.name for f in fields(ColumnPhysicalProps))


def frozen_fk_to_keys() -> frozenset[str]:
    return frozenset(f.name for f in fields(FkToEdgeProps))
