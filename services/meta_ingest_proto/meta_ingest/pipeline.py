from __future__ import annotations

import json
import sys
from typing import Any

from .adapters import extract_catalog
from .adapters.postgres import CATALOG_VERSION
from .catalog_validate import strip_secrets_from_source, validate_catalog_for_ingest
from .config import (
    TargetConfig,
    age_graph_name,
    load_source,
    load_target,
    meta_db_label,
    skip_age_physical,
)
from .sinks.age_psycopg import apply_catalog_to_age_physical
from .sinks.t2s import apply_catalog_to_t2s


def save_catalog(path: str, catalog: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)


def load_catalog(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """로드된 JSON에 누락된 메타키를 보정 (구버전 스냅샷 호환)."""
    strip_secrets_from_source(catalog)
    if not catalog.get("source_engine"):
        catalog["source_engine"] = "postgres"
    for tbl in catalog.get("tables") or []:
        tbl.setdefault("table_type", "BASE TABLE")
    return catalog


def _ingest_audit_line(catalog: dict[str, Any], tgt: TargetConfig | None) -> str:
    """인제스트 감사용 한 줄 (비밀 미포함)."""
    src = catalog.get("source") if isinstance(catalog.get("source"), dict) else {}
    parts = [
        f"meta_db_label={catalog.get('meta_db_label')!r}",
        f"schema={catalog.get('schema')!r}",
        f"source_engine={catalog.get('source_engine')!r}",
        f"source_host={src.get('host')!r}",
        f"source_port={src.get('port')!r}",
        f"source_dbname={src.get('dbname')!r}",
    ]
    if tgt is not None:
        parts.append(f"target={tgt.host!r}:{tgt.port}/{tgt.dbname}")
    return "ingest_audit: " + " ".join(parts)


def cmd_extract(output: str) -> None:
    src = load_source()
    db_label = meta_db_label()
    catalog = extract_catalog(src, db_label)
    validate_catalog_for_ingest(catalog)
    save_catalog(output, catalog)
    nfk = len(catalog.get("foreign_keys") or [])
    print(
        f"Extracted {len(catalog['tables'])} tables, {nfk} FK column-pairs "
        f"to {output!r} (db_label={db_label!r}, schema={catalog['schema']!r}, "
        f"source_engine={catalog.get('source_engine')!r})"
    )
    print(_ingest_audit_line(catalog, None))


def cmd_load(input_path: str) -> None:
    tgt = load_target()
    catalog = normalize_catalog(load_catalog(input_path))
    if catalog.get("version") not in (1, 2, 3, CATALOG_VERSION):
        print("Warning: unexpected catalog version", file=sys.stderr)
    validate_catalog_for_ingest(catalog)
    print(_ingest_audit_line(catalog, tgt))
    t, c, fk = apply_catalog_to_t2s(tgt, catalog)
    msg = (
        f"Loaded catalog from {input_path!r} -> {tgt.host}:{tgt.port}/{tgt.dbname} "
        f"t2s_tables={t} t2s_columns={c} t2s_fk={fk}"
    )
    print(msg)
    if not skip_age_physical():
        ag = apply_catalog_to_age_physical(tgt, catalog)
        print(
            f"AGE {age_graph_name()!r}: Database={ag['database']} Table={ag['tables']} "
            f"Column={ag['columns']} HAS_TABLE={ag['has_table']} HAS_COLUMN={ag['has_column']} "
            f"FK_TO={ag['fk_to']}"
        )
    else:
        print("META_INGEST_SKIP_AGE_PHYSICAL: AGE physical layer skipped.")


def cmd_run_all() -> None:
    src = load_source()
    tgt = load_target()
    db_label = meta_db_label()
    catalog = extract_catalog(src, db_label)
    validate_catalog_for_ingest(catalog)
    print(_ingest_audit_line(catalog, tgt))
    t, c, fk = apply_catalog_to_t2s(tgt, catalog)
    print(
        f"t2s: tables={t} columns={c} fk_pairs={fk} -> {tgt.host}:{tgt.port}/{tgt.dbname}"
    )
    if not skip_age_physical():
        ag = apply_catalog_to_age_physical(tgt, catalog)
        print(
            f"AGE {age_graph_name()!r}: Database={ag['database']} Table={ag['tables']} "
            f"Column={ag['columns']} HAS_TABLE={ag['has_table']} HAS_COLUMN={ag['has_column']} "
            f"FK_TO={ag['fk_to']}"
        )
    else:
        print("META_INGEST_SKIP_AGE_PHYSICAL: AGE physical layer skipped.")
