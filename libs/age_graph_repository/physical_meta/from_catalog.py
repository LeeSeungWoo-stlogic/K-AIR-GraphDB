"""카탈로그 행 → AGE :Table / :Column / FK_TO 속성 맵."""

from __future__ import annotations

from .models import (
    ColumnPhysicalProps,
    DatabasePhysicalProps,
    FkToEdgeProps,
    TablePhysicalProps,
    column_vertex_eid,
    database_vertex_eid,
    table_vertex_eid,
)


def build_database_physical_props(*, meta_db_label: str, source_engine: str) -> dict[str, str | bool]:
    eid = database_vertex_eid(meta_db_label)
    return DatabasePhysicalProps(
        meta_db_label=meta_db_label,
        source_engine=source_engine,
        _meta_ingest=True,
        _physical_vertex_id=eid,
    ).to_age_property_map()


def build_table_physical_props(
    *,
    name: str,
    schema: str,
    description: str,
    analyzed_description: str,
    table_type: str,
    datasource: str,
    db_exists: bool = True,
) -> dict[str, str | bool]:
    eid = table_vertex_eid(datasource, schema, name)
    return TablePhysicalProps(
        name=name,
        schema=schema,
        description=description,
        analyzed_description=analyzed_description,
        table_type=table_type,
        db_exists=db_exists,
        datasource=datasource,
        _meta_ingest=True,
        _physical_vertex_id=eid,
    ).to_age_property_map()


def build_column_physical_props(
    *,
    meta_db_label: str,
    schema: str,
    table_name: str,
    column_name: str,
    dtype: str,
    nullable: bool,
    is_primary_key: bool,
    description: str,
    ordinal_position: int,
    column_default: str,
    is_unique: bool,
) -> dict[str, str | bool | int]:
    fqn = f"{meta_db_label}.{schema}.{table_name}.{column_name}"
    eid = column_vertex_eid(meta_db_label, schema, table_name, column_name)
    return ColumnPhysicalProps(
        name=column_name,
        fqn=fqn,
        dtype=dtype,
        nullable=nullable,
        is_primary_key=is_primary_key,
        description=description,
        ordinal_position=ordinal_position,
        column_default=column_default,
        is_unique=is_unique,
        _meta_ingest=True,
        _physical_vertex_id=eid,
    ).to_age_property_map()


def build_fk_edge_props(*, constraint_name: str | None, position: int) -> dict[str, str | int]:
    return FkToEdgeProps(constraint=constraint_name or "", position=position).to_age_property_map()
