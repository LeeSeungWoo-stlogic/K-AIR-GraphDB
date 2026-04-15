"""
PgRelatedTablesService — related_tables_service.py의 Neo4j 전환.

ROBO 모드: analyzer_table_relationships + FK_TO_TABLE
TEXT2SQL 모드: t2s_fk_constraints + t2s_tables (Phase 3 DDL)
"""

import logging
from typing import Any, Dict, List

import asyncpg

logger = logging.getLogger(__name__)


def build_node_key(mode: str, datasource: str, schema: str, table: str) -> str:
    return f"{mode}:{datasource or ''}:{schema or 'public'}:{table}"


class PgRelatedTablesService:
    """PostgreSQL 기반 관련 테이블 조회 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def fetch_related_tables_unified(self, request: Dict[str, Any]) -> Dict[str, Any]:
        mode = request.get("mode", "ROBO").upper()
        table_name = request["tableName"]
        schema_name = request.get("schemaName", "public")
        datasource_name = request.get("datasourceName", "")
        already_loaded = set(request.get("alreadyLoadedTableIds", []))
        limit = request.get("limit", 5)

        if mode == "ROBO":
            raw = await self._resolve_analyzer(table_name, schema_name)
        else:
            raw = await self._resolve_fabric(table_name, schema_name, datasource_name)

        filtered = [r for r in raw if r["tableId"] not in already_loaded]
        filtered.sort(key=lambda x: x["score"], reverse=True)
        limited = filtered[:limit]

        node_key = request.get("nodeKey") or build_node_key(
            mode.lower(), datasource_name, schema_name, table_name
        )

        return {
            "sourceTable": {
                "tableId": node_key,
                "tableName": table_name,
                "schemaName": schema_name,
                "datasourceName": datasource_name,
            },
            "relatedTables": limited,
            "meta": {"mode": mode, "limitApplied": limit, "excludedAlreadyLoaded": len(raw) - len(filtered)},
        }

    async def _resolve_analyzer(self, table_name: str, schema_name: str) -> List[Dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT t1.name AS from_table, t1.schema_name AS from_schema,
                          t2.name AS to_table, t2.schema_name AS to_schema,
                          r.source_column, r.target_column, r.source
                   FROM analyzer_table_relationships r
                   JOIN analyzer_tables t1 ON t1.id = r.from_table_id
                   JOIN analyzer_tables t2 ON t2.id = r.to_table_id
                   WHERE r.rel_type = 'FK_TO_TABLE'
                     AND ((t1.name = $1 AND COALESCE(t1.schema_name, 'public') = $2)
                       OR (t2.name = $1 AND COALESCE(t2.schema_name, 'public') = $2))""",
                table_name, schema_name,
            )

        table_fks: Dict[tuple, Dict] = {}
        for r in rows:
            ft, fs = r["from_table"], r["from_schema"]
            tt, ts = r["to_table"], r["to_schema"]

            if ft == table_name and (fs or "public") == schema_name:
                related, rs, rel_type = tt, ts, "FK_OUT"
            elif tt == table_name and (ts or "public") == schema_name:
                related, rs, rel_type = ft, fs, "FK_IN"
            else:
                continue

            key = (related, rs or "public")
            if key not in table_fks:
                table_fks[key] = {"relationType": rel_type, "sourceColumns": [], "targetColumns": []}
            if r["source_column"] and r["source_column"] not in table_fks[key]["sourceColumns"]:
                table_fks[key]["sourceColumns"].append(r["source_column"])
            if r["target_column"] and r["target_column"] not in table_fks[key]["targetColumns"]:
                table_fks[key]["targetColumns"].append(r["target_column"])

        items = []
        for (rn, rs), info in table_fks.items():
            nk = build_node_key("robo", "", rs, rn)
            fk_count = max(len(info["sourceColumns"]), len(info["targetColumns"]))
            items.append({
                "tableId": nk,
                "tableName": rn,
                "schemaName": rs,
                "datasourceName": "",
                "relationType": info["relationType"],
                "score": 0.97,
                "fkCount": fk_count,
                "sourceColumns": info["sourceColumns"],
                "targetColumns": info["targetColumns"],
                "autoAddRecommended": True,
            })
        return items

    async def _resolve_fabric(self, table_name: str, schema_name: str, datasource_name: str) -> List[Dict]:
        async with self._pool.acquire() as conn:
            ds_filter = "AND ft1.datasource = $3 AND ft2.datasource = $3" if datasource_name else ""
            args = [table_name, schema_name]
            if datasource_name:
                args.append(datasource_name)

            rows = await conn.fetch(
                f"""SELECT ft1.table_name AS from_table, ft1.schema_name AS from_schema, ft1.datasource AS from_ds,
                           ft2.table_name AS to_table, ft2.schema_name AS to_schema, ft2.datasource AS to_ds,
                           fk.from_column AS source_column, fk.to_column AS target_column
                    FROM t2s_fk_constraints fk
                    JOIN t2s_tables ft1 ON ft1.id = fk.from_table_id
                    JOIN t2s_tables ft2 ON ft2.id = fk.to_table_id
                    WHERE ((ft1.table_name = $1 AND COALESCE(ft1.schema_name, 'public') = $2)
                        OR (ft2.table_name = $1 AND COALESCE(ft2.schema_name, 'public') = $2))
                    {ds_filter}""",
                *args,
            )

        table_fks: Dict[tuple, Dict] = {}
        for r in rows:
            ft, tt = r["from_table"], r["to_table"]
            ds = r["from_ds"] or r["to_ds"] or datasource_name

            if ft == table_name:
                related, rs, rel_type = tt, r["to_schema"], "FK_OUT"
            elif tt == table_name:
                related, rs, rel_type = ft, r["from_schema"], "FK_IN"
            else:
                continue

            key = (related, rs or "public", ds)
            if key not in table_fks:
                table_fks[key] = {"relationType": rel_type, "ds": ds, "sourceColumns": [], "targetColumns": []}
            sc, tc = r["source_column"], r["target_column"]
            if sc and sc not in table_fks[key]["sourceColumns"]:
                table_fks[key]["sourceColumns"].append(sc)
            if tc and tc not in table_fks[key]["targetColumns"]:
                table_fks[key]["targetColumns"].append(tc)

        items = []
        for (rn, rs, ds), info in table_fks.items():
            nk = build_node_key("text2sql", ds, rs, rn)
            fk_count = max(len(info["sourceColumns"]), len(info["targetColumns"]))
            items.append({
                "tableId": nk,
                "tableName": rn,
                "schemaName": rs,
                "datasourceName": ds,
                "relationType": info["relationType"],
                "score": round(0.9 + min(fk_count * 0.02, 0.09), 2),
                "fkCount": fk_count,
                "sourceColumns": info["sourceColumns"],
                "targetColumns": info["targetColumns"],
                "autoAddRecommended": True,
            })
        return items
