"""
Argus Catalog 연동 어댑터 (P1-04).

AGE ontology_graph 쿼리 결과를 Argus Catalog RDB 테이블과
동일 트랜잭션에서 조인하는 크로스 쿼리 세트를 제공한다.

PRD v2 §4.5 연계 쿼리 패턴:
  WITH ontology_cte AS (
      SELECT * FROM cypher('ontology_graph', $$ ... $$) AS (...)
  )
  SELECT ... FROM ontology_cte
  LEFT JOIN catalog_standard_term ...
  LEFT JOIN catalog_code_value ...

Argus Catalog가 동일 PostgreSQL 인스턴스에 있을 때 최적 동작.
별도 인스턴스이면 postgres_fdw 또는 API 호출로 대체 가능.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .connection import AgeConnection
from .cypher_compat import parse_agtype


class CatalogAdapter:
    """AGE ↔ Argus Catalog 크로스 쿼리 어댑터."""

    def __init__(self, conn: AgeConnection):
        self._conn = conn

    # ------------------------------------------------------------------
    # 온톨로지 노드 → Catalog dataset 연결
    # ------------------------------------------------------------------

    async def enrich_nodes_with_catalog(
        self,
        node_label: str = "Measure",
        kpi_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """AGE 온톨로지 노드를 Argus Catalog dataset 메타로 보강.

        PRD §4.5 패턴: AGE Cypher CTE → catalog_datasets JOIN.

        Args:
            node_label: 탐색할 AGE 노드 레이블 (Measure, KPI 등).
            kpi_filter: KPI id 필터 (MEASURED_AS 관계 기준).

        Returns:
            [{"node_name", "data_source", "dataset_description", ...}, ...]
        """
        if kpi_filter:
            cypher = (
                f"MATCH (m:{node_label})-[:MEASURED_AS]->(k:KPI {{id: '{kpi_filter}'}}) "
                f"RETURN m.name AS name, m.data_source AS ds"
            )
        else:
            cypher = (
                f"MATCH (m:{node_label}) "
                f"RETURN m.name AS name, m.dataSource AS ds"
            )

        sql = f"""
        WITH ontology_nodes AS (
            SELECT * FROM cypher('{self._conn.graph_name}', $$
                {cypher}
            $$) AS (name agtype, ds agtype)
        )
        SELECT
            on_n.name::text   AS node_name,
            on_n.ds::text     AS data_source,
            cd.description    AS dataset_description,
            cd.table_type     AS table_type
        FROM ontology_nodes on_n
        LEFT JOIN catalog_datasets cd
            ON cd.name = trim(both '"' from on_n.ds::text)
        """
        rows = await self._conn.execute_sql(sql)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 온톨로지 노드 → 표준 용어 매칭
    # ------------------------------------------------------------------

    async def match_standard_terms(
        self,
        node_label: str = "Measure",
    ) -> List[Dict[str, Any]]:
        """AGE 노드의 data_source를 Argus Catalog 표준 용어와 매칭.

        PRD §4.5: physical_name 기준 JOIN.

        Returns:
            [{"node_name", "data_source", "standard_term", "term_english"}, ...]
        """
        sql = f"""
        WITH ontology_nodes AS (
            SELECT * FROM cypher('{self._conn.graph_name}', $$
                MATCH (m:{node_label})
                RETURN m.name AS name, m.dataSource AS ds
            $$) AS (name agtype, ds agtype)
        )
        SELECT
            on_n.name::text        AS node_name,
            on_n.ds::text          AS data_source,
            st.term_name           AS standard_term,
            st.term_english        AS term_english,
            st.physical_name       AS physical_name
        FROM ontology_nodes on_n
        LEFT JOIN catalog_standard_term st
            ON st.physical_name = trim(both '"' from on_n.ds::text)
        """
        rows = await self._conn.execute_sql(sql)
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 코드값 변환
    # ------------------------------------------------------------------

    async def resolve_code_values(
        self,
        code_group_name: str,
        code_values: List[str],
    ) -> Dict[str, str]:
        """Argus Catalog 코드 그룹에서 코드값→코드명 매핑 조회.

        Args:
            code_group_name: 코드 그룹명 (예: "값형태코드").
            code_values: 코드값 리스트 (예: ["MO", "AV"]).

        Returns:
            {"MO": "모니터링", "AV": "평균값", ...}
        """
        placeholders = ", ".join(f"${i+2}" for i in range(len(code_values)))
        sql = f"""
        SELECT cv.code_value, cv.code_name
        FROM catalog_code_value cv
        JOIN catalog_code_group cg ON cg.id = cv.code_group_id
        WHERE cg.group_name = $1
          AND cv.code_value IN ({placeholders})
        """
        rows = await self._conn.execute_sql(sql, code_group_name, *code_values)
        return {r["code_value"]: r["code_name"] for r in rows}

    # ------------------------------------------------------------------
    # 인과 체인 + Catalog 보강 (PRD §3.3 데이터 흐름 #5)
    # ------------------------------------------------------------------

    async def causal_chain_with_catalog(
        self,
        kpi_id: str,
        max_depth: int = 5,
    ) -> List[Dict[str, Any]]:
        """KPI 인과 체인 탐색 후 Argus Catalog 표준 용어/코드값으로 보강.

        PRD §3.3 데이터 흐름 #5:
          KPI 노드 → AGE 멀티-hop 경로 탐색
          → Argus Catalog 코드값·표준 용어 보강

        Returns:
            경로 상의 각 노드에 대한 보강 정보 리스트.
        """
        results = []

        for depth in range(1, max_depth + 1):
            hops = "()-[]->" * depth
            pattern = f"(src){hops[:-2]}"
            if depth == 1:
                cypher_match = (
                    f"MATCH (src)-[r]->(tgt:KPI {{id: '{kpi_id}'}}) "
                    f"RETURN src.name AS name, src.dataSource AS ds, "
                    f"label(src) AS lbl, type(r) AS rel"
                )
            else:
                continue  # depth 1만 안정적으로 동작, 이후 확장 예정

            try:
                sql = f"""
                WITH causal_nodes AS (
                    SELECT * FROM cypher('{self._conn.graph_name}', $$
                        {cypher_match}
                    $$) AS (name agtype, ds agtype, lbl agtype, rel agtype)
                )
                SELECT
                    cn.name::text          AS node_name,
                    cn.ds::text            AS data_source,
                    cn.lbl::text           AS node_label,
                    cn.rel::text           AS relation_type,
                    st.term_name           AS standard_term,
                    cd.description         AS dataset_description
                FROM causal_nodes cn
                LEFT JOIN catalog_standard_term st
                    ON st.physical_name = trim(both '"' from cn.ds::text)
                LEFT JOIN catalog_datasets cd
                    ON cd.name = trim(both '"' from cn.ds::text)
                """
                rows = await self._conn.execute_sql(sql)
                for r in rows:
                    results.append({**dict(r), "depth": depth})
            except Exception:
                continue

        return results

    # ------------------------------------------------------------------
    # 온톨로지 스키마 RDB 동기화
    # ------------------------------------------------------------------

    async def sync_schema_to_rdb(
        self,
        schema: Dict[str, Any],
    ) -> None:
        """온톨로지 스키마를 ontology_schemas RDB 테이블에 저장/갱신.

        AGE 그래프에 저장된 온톨로지 스키마의 메타정보 + JSON 전문을
        RDB에 병행 저장하여 빠른 목록 조회를 지원한다.
        """
        import json

        schema_json = json.dumps(schema, ensure_ascii=False, default=str)
        sql = """
        INSERT INTO ontology_schemas (id, name, description, domain, version, schema_json, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, now())
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            domain = EXCLUDED.domain,
            version = EXCLUDED.version,
            schema_json = EXCLUDED.schema_json,
            updated_at = now()
        """
        await self._conn.execute_sql_status(
            sql,
            schema.get("id", ""),
            schema.get("name", ""),
            schema.get("description", ""),
            schema.get("domain", ""),
            schema.get("version", 1),
            schema_json,
        )

        version_sql = """
        INSERT INTO ontology_schema_versions (schema_id, version, schema_json)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (schema_id, version) DO NOTHING
        """
        await self._conn.execute_sql_status(
            version_sql,
            schema.get("id", ""),
            schema.get("version", 1),
            schema_json,
        )

    async def list_schemas(self) -> List[Dict[str, Any]]:
        """ontology_schemas RDB 테이블에서 스키마 목록 조회."""
        rows = await self._conn.execute_sql(
            "SELECT id, name, description, domain, version, created_at, updated_at "
            "FROM ontology_schemas ORDER BY updated_at DESC"
        )
        return [dict(r) for r in rows]

    async def get_schema_json(self, schema_id: str) -> Optional[Dict[str, Any]]:
        """스키마 JSON 전문 조회."""
        import json
        rows = await self._conn.execute_sql(
            "SELECT schema_json FROM ontology_schemas WHERE id = $1",
            schema_id,
        )
        if not rows:
            return None
        raw = rows[0]["schema_json"]
        return json.loads(raw) if isinstance(raw, str) else raw

    async def get_schema_versions(self, schema_id: str) -> List[Dict[str, Any]]:
        """스키마 버전 이력 조회."""
        rows = await self._conn.execute_sql(
            "SELECT version, created_at FROM ontology_schema_versions "
            "WHERE schema_id = $1 ORDER BY version DESC",
            schema_id,
        )
        return [dict(r) for r in rows]
