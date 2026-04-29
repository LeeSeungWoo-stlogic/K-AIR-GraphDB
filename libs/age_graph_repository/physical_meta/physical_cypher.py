"""카탈로그 dict → AGE 물리층 갱신용 Cypher 문장 나열 (계약 빌더 사용).

execute_cypher( inner ) 형태로 실행할 **내부** Cypher만 생성한다.
"""

from __future__ import annotations

import json
from typing import Any

from .from_catalog import build_column_physical_props, build_fk_edge_props, build_table_physical_props
from .models import column_vertex_eid, table_vertex_eid


def _json_default(o: Any) -> str:
    try:
        return o.isoformat()  # type: ignore[attr-defined]
    except Exception:
        pass
    return str(o)


def _age_escape_str(s: str | None) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", " ")


def _build_age_props(props: dict[str, Any]) -> str:
    parts: list[str] = []
    for k, v in props.items():
        if v is None:
            continue
        if isinstance(v, bool):
            parts.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif isinstance(v, str):
            parts.append(f"{k}: '{_age_escape_str(v)}'")
        else:
            try:
                s = json.dumps(v, ensure_ascii=False, default=_json_default)
            except Exception:
                s = str(v)
            parts.append(f"{k}: '{_age_escape_str(s)}'")
    return "{" + ", ".join(parts) + "}"


def _format_dtype(r: dict[str, Any]) -> str:
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


def _column_default_str(r: dict[str, Any]) -> str:
    v = r.get("column_default")
    if v is None:
        return ""
    return str(v).strip()


def build_physical_meta_refresh(
    catalog: dict[str, Any],
) -> tuple[list[str], dict[str, int]]:
    """_meta_ingest 마킹 Table/Column/FK_TO 재적재용 Cypher 목록.

    Returns:
        (cypher_inner_statements, summary_counts)
    """
    db_label = catalog["meta_db_label"]
    schema = catalog["schema"]
    pks = {tuple(pair) for pair in catalog["primary_keys"]}
    fk_list = catalog.get("foreign_keys") or []
    table_names = {t["name"] for t in catalog["tables"]}

    statements: list[str] = []
    summary = {"tables": 0, "columns": 0, "has_column": 0, "fk_to": 0}

    statements.append(
        "MATCH (c:Column) WHERE c._meta_ingest = true DETACH DELETE c"
    )
    statements.append(
        "MATCH (t:Table) WHERE t._meta_ingest = true DETACH DELETE t"
    )

    for tbl in catalog["tables"]:
        tname = tbl["name"]
        teid = table_vertex_eid(db_label, schema, tname)
        tab_comment = tbl.get("comment") or ""
        tprops = build_table_physical_props(
            name=tname,
            schema=schema,
            description=tab_comment,
            analyzed_description="",
            table_type=tbl.get("table_type") or "",
            datasource=db_label,
            db_exists=True,
        )
        p = dict(tprops)
        p["_neo4j_eid"] = teid
        lit = _build_age_props(p)
        statements.append(f"CREATE (: `Table` {lit})")
        summary["tables"] += 1

        for r in tbl["columns"]:
            cname = r["column_name"]
            ceid = column_vertex_eid(db_label, schema, tname, cname)
            nullable = (r.get("is_nullable") or "YES").upper() == "YES"
            is_pkey = (tname, cname) in pks
            desc = r.get("col_comment") or ""
            ordinal = int(r.get("ordinal_position") or 0)
            is_unique = bool(r.get("is_unique", False))
            cprops = build_column_physical_props(
                meta_db_label=db_label,
                schema=schema,
                table_name=tname,
                column_name=cname,
                dtype=_format_dtype(r),
                nullable=nullable,
                is_primary_key=is_pkey,
                description=desc,
                ordinal_position=ordinal,
                column_default=_column_default_str(r),
                is_unique=is_unique,
            )
            p2 = dict(cprops)
            p2["_neo4j_eid"] = ceid
            lit_c = _build_age_props(p2)
            statements.append(f"CREATE (: `Column` {lit_c})")
            summary["columns"] += 1
            esc_te = _age_escape_str(teid)
            esc_ce = _age_escape_str(ceid)
            statements.append(
                f"MATCH (a), (b) WHERE a._neo4j_eid = '{esc_te}' "
                f"AND b._neo4j_eid = '{esc_ce}' CREATE (a)-[:HAS_COLUMN {{}}]->(b)"
            )
            summary["has_column"] += 1

    for fk in fk_list:
        if fk.get("from_schema") != schema or fk.get("to_schema") != schema:
            continue
        if fk["from_table"] not in table_names or fk["to_table"] not in table_names:
            continue
        from_eid = column_vertex_eid(db_label, schema, fk["from_table"], fk["from_column"])
        to_eid = column_vertex_eid(db_label, schema, fk["to_table"], fk["to_column"])
        pos = int(fk.get("position") or 1)
        fk_props = build_fk_edge_props(
            constraint_name=fk.get("constraint_name"),
            position=pos,
        )
        prop_lit = _build_age_props(fk_props)
        esc_f = _age_escape_str(from_eid)
        esc_t = _age_escape_str(to_eid)
        statements.append(
            f"MATCH (a), (b) WHERE a._neo4j_eid = '{esc_f}' "
            f"AND b._neo4j_eid = '{esc_t}' CREATE (a)-[:FK_TO {prop_lit}]->(b)"
        )
        summary["fk_to"] += 1

    return statements, summary
