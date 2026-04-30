from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from ..adapters.postgres import format_dtype
from ..config import TargetConfig, dsn_pg


def apply_catalog_to_t2s(
    tgt: TargetConfig, catalog: dict[str, Any]
) -> tuple[int, int, int]:
    db_label = catalog["meta_db_label"]
    schema = catalog["schema"]
    pks = {tuple(pair) for pair in catalog["primary_keys"]}
    fk_list = catalog.get("foreign_keys") or []
    table_names = {t["name"] for t in catalog["tables"]}

    upsert_table = """
    INSERT INTO t2s_tables (db, schema_name, name, original_name, comment, metadata)
    VALUES (%(db)s, %(schema_name)s, %(name)s, %(original_name)s, %(comment)s, %(metadata)s)
    ON CONFLICT (db, schema_name, name) DO UPDATE SET
      original_name = EXCLUDED.original_name,
      comment = EXCLUDED.comment,
      metadata = t2s_tables.metadata || EXCLUDED.metadata,
      updated_at = now()
    RETURNING id;
    """

    upsert_column = """
    INSERT INTO t2s_columns (
      table_id, name, fqn, dtype, nullable, description, is_primary_key, metadata
    )
    VALUES (
      %(table_id)s, %(name)s, %(fqn)s, %(dtype)s, %(nullable)s, %(description)s, %(is_pkey)s, %(metadata)s
    )
    ON CONFLICT (fqn) DO UPDATE SET
      dtype = EXCLUDED.dtype,
      nullable = EXCLUDED.nullable,
      description = EXCLUDED.description,
      is_primary_key = EXCLUDED.is_primary_key,
      metadata = t2s_columns.metadata || EXCLUDED.metadata,
      updated_at = now()
    RETURNING id;
    """

    inserted_tables = 0
    inserted_cols = 0
    fqn_to_col_id: dict[str, int] = {}

    with psycopg.connect(dsn_pg(tgt, tgt.dbname)) as tconn:
        with tconn.transaction():
            for tbl in catalog["tables"]:
                table_name = tbl["name"]
                tab_comment = tbl.get("comment") or ""
                meta = {
                    "source": "meta_ingest_proto_catalog",
                    "catalog_version": catalog.get("version"),
                    "contract_version": catalog.get("contract_version"),
                    "source_snapshot": catalog.get("source"),
                    "source_engine": catalog.get("source_engine"),
                }
                with tconn.cursor() as cur:
                    cur.execute(
                        upsert_table,
                        {
                            "db": db_label,
                            "schema_name": schema,
                            "name": table_name,
                            "original_name": table_name,
                            "comment": tab_comment,
                            "metadata": Json(meta),
                        },
                    )
                    tid = cur.fetchone()[0]
                inserted_tables += 1
                for r in tbl["columns"]:
                    cname = r["column_name"]
                    fqn = f"{db_label}.{schema}.{table_name}.{cname}"
                    nullable = (r.get("is_nullable") or "YES").upper() == "YES"
                    is_pkey = (table_name, cname) in pks
                    desc = r.get("col_comment") or ""
                    col_meta = {
                        "ordinal_position": r.get("ordinal_position"),
                        "column_default": r.get("column_default"),
                        "is_unique": bool(r.get("is_unique", False)),
                    }
                    with tconn.cursor() as cur:
                        cur.execute(
                            upsert_column,
                            {
                                "table_id": tid,
                                "name": cname,
                                "fqn": fqn,
                                "dtype": format_dtype(r),
                                "nullable": nullable,
                                "description": desc,
                                "is_pkey": is_pkey,
                                "metadata": Json(col_meta),
                            },
                        )
                        fqn_to_col_id[fqn] = cur.fetchone()[0]
                    inserted_cols += 1

            fk_inserted = 0
            for fk in fk_list:
                if fk.get("from_schema") != schema or fk.get("to_schema") != schema:
                    continue
                if fk["from_table"] not in table_names or fk["to_table"] not in table_names:
                    continue
                ffqn = f"{db_label}.{schema}.{fk['from_table']}.{fk['from_column']}"
                tfqn = f"{db_label}.{schema}.{fk['to_table']}.{fk['to_column']}"
                from_id = fqn_to_col_id.get(ffqn)
                to_id = fqn_to_col_id.get(tfqn)
                if from_id is None or to_id is None:
                    continue
                with tconn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO t2s_fk_constraints (from_column_id, to_column_id, constraint_name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (from_column_id, to_column_id) DO NOTHING
                        """,
                        (from_id, to_id, fk.get("constraint_name") or ""),
                    )
                    fk_inserted += cur.rowcount

    return inserted_tables, inserted_cols, fk_inserted
