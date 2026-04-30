"""AGE 물리 메타 그래프(Database / Table / Column / HAS_TABLE / HAS_COLUMN / FK_TO) 속성 계약 — 온톨로지·AI 증강 제외."""

from .from_catalog import (
    build_column_physical_props,
    build_database_physical_props,
    build_fk_edge_props,
    build_table_physical_props,
)
from .models import (
    ColumnPhysicalProps,
    DatabasePhysicalProps,
    FkToEdgeProps,
    TablePhysicalProps,
    column_vertex_eid,
    database_vertex_eid,
    table_vertex_eid,
    frozen_column_keys,
    frozen_database_keys,
    frozen_fk_to_keys,
    frozen_table_keys,
)
from .validation import (
    validate_age_column_props,
    validate_age_database_props,
    validate_age_fk_props,
    validate_age_table_props,
    validate_has_column_empty,
)
from .physical_cypher import build_physical_meta_refresh
from .version import PHYSICAL_META_CONTRACT_VERSION

__all__ = [
    "PHYSICAL_META_CONTRACT_VERSION",
    "DatabasePhysicalProps",
    "TablePhysicalProps",
    "ColumnPhysicalProps",
    "FkToEdgeProps",
    "database_vertex_eid",
    "table_vertex_eid",
    "column_vertex_eid",
    "frozen_table_keys",
    "frozen_database_keys",
    "frozen_column_keys",
    "frozen_fk_to_keys",
    "build_database_physical_props",
    "build_table_physical_props",
    "build_column_physical_props",
    "build_fk_edge_props",
    "validate_age_database_props",
    "validate_age_table_props",
    "validate_age_column_props",
    "validate_age_fk_props",
    "validate_has_column_empty",
    "build_physical_meta_refresh",
]
