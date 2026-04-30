from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from age_graph_repository.physical_meta import PHYSICAL_META_CONTRACT_VERSION

from ..config import SourceConfig, dsn_pg
from .base import CatalogExtractor


class PostgresCatalogExtractor(CatalogExtractor):
    source_engine = "postgres"

    def extract(self, src: SourceConfig, db_label: str) -> dict[str, Any]:
        return build_catalog_dict(src, db_label)


def fetch_columns(src: SourceConfig) -> list[dict[str, Any]]:
    sql = """
    SELECT
      c.table_schema,
      c.table_name,
      c.column_name,
      c.ordinal_position,
      c.data_type,
      c.udt_name,
      c.character_maximum_length,
      c.numeric_precision,
      c.numeric_scale,
      c.is_nullable,
      c.column_default,
      pgd.description AS col_comment
    FROM information_schema.columns c
    LEFT JOIN pg_catalog.pg_namespace n
      ON n.nspname = c.table_schema
    LEFT JOIN pg_catalog.pg_class pc
      ON pc.relnamespace = n.oid AND pc.relname = c.table_name AND pc.relkind = 'r'
    LEFT JOIN pg_catalog.pg_attribute a
      ON a.attrelid = pc.oid AND a.attname = c.column_name AND NOT a.attisdropped
    LEFT JOIN pg_catalog.pg_description pgd
      ON pgd.objoid = pc.oid AND pgd.objsubid = a.attnum
    WHERE c.table_schema = %s
    ORDER BY c.table_name, c.ordinal_position;
    """
    with psycopg.connect(dsn_pg(src, src.dbname), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src.schema,))
            return list(cur.fetchall())


def fetch_foreign_keys(src: SourceConfig) -> list[dict[str, Any]]:
    sql = """
    SELECT
      c.conname AS constraint_name,
      nfs.nspname AS from_schema,
      nrf.relname AS from_table,
      attf.attname AS from_column,
      nts.nspname AS to_schema,
      ntr.relname AS to_table,
      attt.attname AS to_column
    FROM pg_constraint c
    JOIN pg_class nrf ON nrf.oid = c.conrelid
    JOIN pg_namespace nfs ON nfs.oid = nrf.relnamespace
    JOIN pg_class ntr ON ntr.oid = c.confrelid
    JOIN pg_namespace nts ON nts.oid = ntr.relnamespace
    CROSS JOIN LATERAL unnest(c.conkey, c.confkey) AS u(att, confatt)
    JOIN pg_attribute attf
      ON attf.attrelid = c.conrelid AND attf.attnum = u.att AND NOT attf.attisdropped
    JOIN pg_attribute attt
      ON attt.attrelid = c.confrelid AND attt.attnum = u.confatt AND NOT attt.attisdropped
    WHERE c.contype = 'f' AND nfs.nspname = %s
    ORDER BY c.conname, u.att;
    """
    with psycopg.connect(dsn_pg(src, src.dbname), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src.schema,))
            return [dict(r) for r in cur.fetchall()]


def fetch_table_comments(src: SourceConfig) -> dict[tuple[str, str], str | None]:
    sql = """
    SELECT n.nspname AS schema_name, c.relname AS table_name, d.description
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_catalog.pg_description d ON d.objoid = c.oid AND d.objsubid = 0
    WHERE c.relkind = 'r' AND n.nspname = %s;
    """
    with psycopg.connect(dsn_pg(src, src.dbname)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src.schema,))
            rows = cur.fetchall()
    out: dict[tuple[str, str], str | None] = {}
    for schema_name, table_name, desc in rows:
        out[(schema_name, table_name)] = desc
    return out


def fetch_primary_key(src: SourceConfig) -> set[tuple[str, str]]:
    sql = """
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_catalog = kcu.constraint_catalog
     AND tc.constraint_schema = kcu.constraint_schema
     AND tc.constraint_name = kcu.constraint_name
    WHERE tc.table_schema = %s AND tc.constraint_type = 'PRIMARY KEY';
    """
    with psycopg.connect(dsn_pg(src, src.dbname)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src.schema,))
            rows = cur.fetchall()
    return {(t, c) for (t, c) in rows}


def fetch_unique_columns(src: SourceConfig) -> set[tuple[str, str]]:
    sql = """
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_catalog = kcu.constraint_catalog
     AND tc.constraint_schema = kcu.constraint_schema
     AND tc.constraint_name = kcu.constraint_name
    WHERE tc.table_schema = %s AND tc.constraint_type = 'UNIQUE';
    """
    with psycopg.connect(dsn_pg(src, src.dbname)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src.schema,))
            rows = cur.fetchall()
    return {(t, c) for (t, c) in rows}


def format_dtype(r: dict[str, Any]) -> str:
    dt = r.get("data_type") or ""
    udt = r.get("udt_name") or ""
    cmax = r.get("character_maximum_length")
    prec = r.get("numeric_precision")
    scale = r.get("numeric_scale")
    base = str(dt)
    if base == "character varying" and cmax:
        return f"varchar({cmax})"
    if base == "character" and cmax:
        return f"char({cmax})"
    if base == "numeric" and prec is not None:
        if scale is not None:
            return f"numeric({prec},{scale})"
        return f"numeric({prec})"
    if udt and udt != dt:
        return f"{base}({udt})" if base else str(udt)
    return base


CATALOG_VERSION = 3


def build_catalog_dict(src: SourceConfig, db_label: str) -> dict[str, Any]:
    cols = fetch_columns(src)
    if not cols:
        raise RuntimeError(
            f"No columns for schema={src.schema!r} on {src.host}:{src.port}/{src.dbname}"
        )
    tab_comments = fetch_table_comments(src)
    pks = fetch_primary_key(src)
    uniq = fetch_unique_columns(src)
    fks = fetch_foreign_keys(src)
    by_table: dict[str, list[dict[str, Any]]] = {}
    for r in cols:
        by_table.setdefault(r["table_name"], []).append(dict(r))
    tables_list: list[dict[str, Any]] = []
    for table_name in sorted(by_table):
        enriched_cols: list[dict[str, Any]] = []
        for r in by_table[table_name]:
            d = dict(r)
            d["is_unique"] = (table_name, r["column_name"]) in uniq
            enriched_cols.append(d)
        tables_list.append(
            {
                "name": table_name,
                "comment": tab_comments.get((src.schema, table_name)) or "",
                "table_type": "BASE TABLE",
                "columns": enriched_cols,
            }
        )
    pos_by_constraint_from_table: dict[tuple[str, str], int] = {}
    fk_rows: list[dict[str, Any]] = []
    for r in fks:
        cn = str(r.get("constraint_name") or "")
        ft = str(r["from_table"])
        key = (cn, ft)
        pos_by_constraint_from_table[key] = pos_by_constraint_from_table.get(key, 0) + 1
        fk_rows.append(
            {
                "constraint_name": r["constraint_name"],
                "from_schema": r["from_schema"],
                "from_table": r["from_table"],
                "from_column": r["from_column"],
                "to_schema": r["to_schema"],
                "to_table": r["to_table"],
                "to_column": r["to_column"],
                "position": pos_by_constraint_from_table[key],
            }
        )
    return {
        "version": CATALOG_VERSION,
        "contract_version": PHYSICAL_META_CONTRACT_VERSION,
        "meta_db_label": db_label,
        "schema": src.schema,
        "source_engine": PostgresCatalogExtractor.source_engine,
        "source": {
            "host": src.host,
            "port": src.port,
            "dbname": src.dbname,
        },
        "tables": tables_list,
        "primary_keys": sorted([list(x) for x in pks]),
        "foreign_keys": fk_rows,
    }
