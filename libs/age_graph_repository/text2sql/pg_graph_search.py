"""
pgvector + SQL 기반 그래프 검색 — GraphSearcher drop-in 대체.

Neo4j의 CALL db.index.vector.queryNodes + MATCH 패턴을
pgvector HNSW 코사인 유사도 + SQL JOIN으로 전환한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .pg_connection import PgConnection


def _vec_str(v: list) -> Optional[str]:
    if not v:
        return None
    return "[" + ",".join(str(float(x)) for x in v) + "]"


@dataclass
class TableMatch:
    name: str
    schema: str
    db: str
    description: str
    analyzed_description: str = ""
    score: float = 0.0
    columns: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ColumnMatch:
    name: str
    table_name: str
    table_schema: str
    db: str
    dtype: str
    description: str
    score: float
    nullable: bool = True


@dataclass
class SubSchema:
    tables: List[TableMatch]
    columns: List[ColumnMatch]
    fk_relationships: List[Dict[str, Any]]
    join_hints: List[str]


class PgGraphSearcher:
    """pgvector + SQL 기반 스키마 검색 (GraphSearcher 대체)."""

    def __init__(self, pg_conn: PgConnection, *, top_k: int = 10, max_hops: int = 3):
        self._pg = pg_conn
        self.top_k = top_k
        self.max_hops = max_hops

    async def search_tables(
        self,
        query_embedding: List[float],
        k: Optional[int] = None,
        schema_filter: Optional[List[str]] = None,
        datasource: Optional[str] = None,
    ) -> List[TableMatch]:
        k = k or self.top_k
        fetch_k = k * 3 if schema_filter else k

        conditions = ["vector IS NOT NULL"]
        args: list = [_vec_str(query_embedding), fetch_k]
        idx = 3
        if schema_filter:
            sf_lower = [s.lower() for s in schema_filter]
            conditions.append(f"lower(schema_name) = ANY(${idx})")
            args.append(sf_lower)
            idx += 1
        if datasource and datasource.strip():
            conditions.append(f"lower(db) = lower(${idx})")
            args.append(datasource.strip())
            idx += 1

        where = " AND ".join(conditions)
        sql = f"""
        SELECT COALESCE(original_name, name) AS name,
               schema_name AS schema, db,
               COALESCE(description, '') AS description,
               COALESCE(analyzed_description, '') AS analyzed_description,
               1 - (vector <=> $1::vector) AS score
        FROM t2s_tables
        WHERE {where}
        ORDER BY vector <=> $1::vector
        LIMIT $2
        """
        rows = await self._pg.fetch(sql, *args)
        matches = [
            TableMatch(
                name=r["name"], schema=r["schema"], db=r["db"],
                description=r["description"],
                analyzed_description=r["analyzed_description"],
                score=float(r["score"]),
            )
            for r in rows
        ]
        return matches[:k]

    async def search_columns(
        self,
        query_embedding: List[float],
        k: Optional[int] = None,
        schema_filter: Optional[List[str]] = None,
        datasource: Optional[str] = None,
    ) -> List[ColumnMatch]:
        k = k or self.top_k
        fetch_k = k * 3 if schema_filter else k

        conditions = ["c.vector IS NOT NULL"]
        args: list = [_vec_str(query_embedding), fetch_k]
        idx = 3
        if schema_filter:
            sf_lower = [s.lower() for s in schema_filter]
            conditions.append(f"lower(t.schema_name) = ANY(${idx})")
            args.append(sf_lower)
            idx += 1
        if datasource and datasource.strip():
            conditions.append(f"lower(t.db) = lower(${idx})")
            args.append(datasource.strip())
            idx += 1

        where = " AND ".join(conditions)
        sql = f"""
        SELECT c.name, t.name AS table_name, t.schema_name AS table_schema,
               t.db, c.dtype, COALESCE(c.description, '') AS description,
               c.nullable,
               1 - (c.vector <=> $1::vector) AS score
        FROM t2s_columns c
        JOIN t2s_tables t ON t.id = c.table_id
        WHERE {where}
        ORDER BY c.vector <=> $1::vector
        LIMIT $2
        """
        rows = await self._pg.fetch(sql, *args)
        return [
            ColumnMatch(
                name=r["name"], table_name=r["table_name"],
                table_schema=r["table_schema"], db=r["db"],
                dtype=r["dtype"], description=r["description"],
                nullable=r["nullable"], score=float(r["score"]),
            )
            for r in rows
        ][:k]

    async def find_fk_paths(self, table_keys: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        if len(table_keys) < 2:
            return []
        keys = [f"{t.get('db', '')}|{t.get('schema', '')}|{t.get('name', '')}" for t in table_keys]
        rows = await self._pg.fetch(
            """
            SELECT
              t1.schema_name || '.' || COALESCE(t1.original_name, t1.name) AS from_table,
              t2.schema_name || '.' || COALESCE(t2.original_name, t2.name) AS to_table,
              1 AS path_length,
              ARRAY['FK_TO'] AS relationship_types
            FROM t2s_fk_constraints fk
            JOIN t2s_columns c1 ON c1.id = fk.from_column_id
            JOIN t2s_columns c2 ON c2.id = fk.to_column_id
            JOIN t2s_tables t1 ON t1.id = c1.table_id
            JOIN t2s_tables t2 ON t2.id = c2.table_id
            WHERE (t1.db || '|' || t1.schema_name || '|' || t1.name) = ANY($1)
              AND (t2.db || '|' || t2.schema_name || '|' || t2.name) = ANY($1)
              AND t1.id <> t2.id
            ORDER BY from_table, to_table
            LIMIT 20
            """,
            keys,
        )
        return [dict(r) for r in rows]

    async def get_table_columns(self, table_keys: List[Dict[str, str]]) -> Dict[str, List[Dict[str, Any]]]:
        if not table_keys:
            return {}
        keys = [(t.get("db", ""), t.get("schema", ""), t.get("name", "")) for t in table_keys]
        db_list = [k[0] for k in keys]
        schema_list = [k[1] for k in keys]
        name_list = [k[2] for k in keys]

        rows = await self._pg.fetch(
            """
            SELECT t.schema_name AS schema, t.name AS table_name,
                   c.name, c.dtype, c.nullable, c.description
            FROM t2s_tables t
            JOIN t2s_columns c ON c.table_id = t.id
            WHERE (t.db, t.schema_name, t.name) IN (
                SELECT unnest($1::text[]), unnest($2::text[]), unnest($3::text[])
            )
            ORDER BY t.schema_name, t.name, c.name
            """,
            db_list, schema_list, name_list,
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            key = f"{r['schema']}.{r['table_name']}".strip(".").lower()
            if key not in out:
                out[key] = []
            out[key].append({
                "name": r["name"], "dtype": r["dtype"],
                "nullable": r["nullable"], "description": r["description"],
            })
        return out

    async def get_fk_details(self, table_keys: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        keys = [f"{t.get('db', '')}|{t.get('schema', '')}|{t.get('name', '')}" for t in (table_keys or [])]
        rows = await self._pg.fetch(
            """
            SELECT
              t1.schema_name || '.' || COALESCE(t1.original_name, t1.name) AS from_table,
              c1.name AS from_column,
              t2.schema_name || '.' || COALESCE(t2.original_name, t2.name) AS to_table,
              c2.name AS to_column,
              fk.constraint_name
            FROM t2s_fk_constraints fk
            JOIN t2s_columns c1 ON c1.id = fk.from_column_id
            JOIN t2s_columns c2 ON c2.id = fk.to_column_id
            JOIN t2s_tables t1 ON t1.id = c1.table_id
            JOIN t2s_tables t2 ON t2.id = c2.table_id
            WHERE (t1.db || '|' || t1.schema_name || '|' || t1.name) = ANY($1)
              AND (t2.db || '|' || t2.schema_name || '|' || t2.name) = ANY($1)
            """,
            keys,
        )
        return [dict(r) for r in rows]

    async def build_subschema(
        self,
        query_embedding: List[float],
        top_k_tables: Optional[int] = None,
        top_k_columns: Optional[int] = None,
        datasource: Optional[str] = None,
        schema_filter: Optional[List[str]] = None,
    ) -> SubSchema:
        top_k_tables = top_k_tables or self.top_k
        top_k_columns = top_k_columns or self.top_k

        table_matches = await self.search_tables(
            query_embedding, k=top_k_tables, schema_filter=schema_filter, datasource=datasource
        )
        column_matches = await self.search_columns(
            query_embedding, k=top_k_columns, schema_filter=schema_filter, datasource=datasource
        )

        table_keys_set = set()
        for t in table_matches:
            if t.name and t.schema and t.db:
                table_keys_set.add((t.db, t.schema, t.name))
        for c in column_matches:
            if c.table_name and c.table_schema and c.db:
                table_keys_set.add((c.db, c.table_schema, c.table_name))
        table_keys = [
            {"db": db, "schema": schema, "name": name}
            for (db, schema, name) in sorted(table_keys_set)
        ]

        table_columns = await self.get_table_columns(table_keys)
        for table in table_matches:
            key = f"{table.schema}.{table.name}".strip(".").lower()
            table.columns = table_columns.get(key, [])

        fk_paths = await self.find_fk_paths(table_keys)
        fk_details = await self.get_fk_details(table_keys)
        join_hints = self._generate_join_hints(fk_details)

        return SubSchema(
            tables=table_matches,
            columns=column_matches,
            fk_relationships=fk_details,
            join_hints=join_hints,
        )

    @staticmethod
    def _generate_join_hints(fk_details: List[Dict[str, Any]]) -> List[str]:
        hints = []
        for fk in fk_details:
            hint = (
                f"JOIN {fk['to_table']} ON {fk['from_table']}.{fk['from_column']} = "
                f"{fk['to_table']}.{fk['to_column']}"
            )
            hints.append(hint)
        return hints


def format_subschema_for_prompt(subschema: SubSchema) -> str:
    lines = []
    lines.append("=== Available Tables ===")
    for table in subschema.tables:
        lines.append(f"\nTable: {table.schema}.{table.name}")
        if table.description:
            lines.append(f"  Description: {table.description}")
        if table.columns:
            lines.append("  Columns:")
            for col in table.columns:
                null_str = "NULL" if col.get("nullable") else "NOT NULL"
                desc = col.get("description", "")
                col_line = f"    - {col['name']} ({col['dtype']}, {null_str})"
                if desc:
                    col_line += f" - {desc}"
                lines.append(col_line)

    if subschema.fk_relationships:
        lines.append("\n=== Foreign Key Relationships ===")
        for fk in subschema.fk_relationships:
            lines.append(
                f"  {fk['from_table']}.{fk['from_column']} -> "
                f"{fk['to_table']}.{fk['to_column']}"
            )

    if subschema.join_hints:
        lines.append("\n=== Suggested Joins ===")
        for hint in subschema.join_hints:
            lines.append(f"  {hint}")

    return "\n".join(lines)
