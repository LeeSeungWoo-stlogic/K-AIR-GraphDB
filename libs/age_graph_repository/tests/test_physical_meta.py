"""physical_meta 계약 단위 테스트 (DB 불필요)."""

from __future__ import annotations

import pytest

from age_graph_repository.physical_meta import (
    PHYSICAL_META_CONTRACT_VERSION,
    build_column_physical_props,
    build_database_physical_props,
    build_fk_edge_props,
    build_physical_meta_refresh,
    build_table_physical_props,
    column_vertex_eid,
    database_vertex_eid,
    frozen_column_keys,
    frozen_database_keys,
    frozen_fk_to_keys,
    frozen_table_keys,
    table_vertex_eid,
    validate_age_column_props,
    validate_age_database_props,
    validate_age_fk_props,
    validate_age_table_props,
    validate_has_column_empty,
)


def test_version():
    assert PHYSICAL_META_CONTRACT_VERSION == "1.1.0"


def test_frozen_key_sets():
    assert "ordinal_position" in frozen_column_keys()
    assert "column_default" in frozen_column_keys()
    assert "is_unique" in frozen_column_keys()
    assert "meta_db_label" in frozen_database_keys()
    assert "source_engine" in frozen_database_keys()
    assert "position" in frozen_fk_to_keys()


def test_builders_validate():
    validate_age_database_props(
        build_database_physical_props(meta_db_label="lab", source_engine="postgres")
    )
    validate_age_table_props(
        build_table_physical_props(
            name="T",
            schema="S",
            description="",
            analyzed_description="",
            table_type="",
            datasource="lab",
        )
    )
    validate_age_column_props(
        build_column_physical_props(
            meta_db_label="lab",
            schema="S",
            table_name="T",
            column_name="c",
            dtype="int",
            nullable=True,
            is_primary_key=False,
            description="",
            ordinal_position=1,
            column_default="",
            is_unique=False,
        )
    )
    validate_age_fk_props(build_fk_edge_props(constraint_name="fk", position=2))


def test_eids():
    assert database_vertex_eid("a") == "meta_ingest:D:a"
    assert table_vertex_eid("a", "b", "c") == "meta_ingest:T:a:b:c"
    assert column_vertex_eid("a", "b", "c", "d") == "meta_ingest:C:a:b:c:d"


def test_has_column_empty_ok():
    validate_has_column_empty({})


def test_extra_table_key_rejected():
    m = build_table_physical_props(
        name="t",
        schema="s",
        description="",
        analyzed_description="",
        table_type="",
        datasource="ds",
    )
    m["bad"] = True
    with pytest.raises(ValueError):
        validate_age_table_props(m)


def test_build_physical_meta_refresh_smoke():
    catalog = {
        "meta_db_label": "lab",
        "schema": "S",
        "source_engine": "postgres",
        "primary_keys": [["t", "id"]],
        "foreign_keys": [],
        "tables": [
            {
                "name": "t",
                "comment": "hi",
                "columns": [
                    {
                        "column_name": "id",
                        "ordinal_position": 1,
                        "data_type": "integer",
                        "udt_name": "int4",
                        "character_maximum_length": None,
                        "numeric_precision": None,
                        "numeric_scale": None,
                        "is_nullable": "NO",
                        "column_default": None,
                        "col_comment": "",
                        "is_unique": False,
                    }
                ],
            }
        ],
    }
    cyphers, summary = build_physical_meta_refresh(catalog)
    assert cyphers[0].startswith("MATCH (c:Column)")
    assert cyphers[1].startswith("MATCH (t:Table)")
    assert cyphers[2].startswith("MATCH (d:Database)")
    assert "CREATE (: `Database`" in cyphers[3]
    assert any("CREATE (: `Table`" in s for s in cyphers)
    assert any("HAS_TABLE" in s for s in cyphers)
    assert any("CREATE (: `Column`" in s for s in cyphers)
    assert summary == {
        "database": 1,
        "tables": 1,
        "columns": 1,
        "has_table": 1,
        "has_column": 1,
        "fk_to": 0,
    }
