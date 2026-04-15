"""
AgeGraphRepository — Neo4j Neo4jService 1:1 대체.

Neo4jService의 퍼블릭 인터페이스를 보존하면서,
백엔드를 Apache AGE (asyncpg) 로 교체한다.

지원 기능:
  - sync_ontology_schema: 온톨로지 스키마 전체를 AGE 그래프에 동기화
  - get_ontology_nodes: 온톨로지 노드 목록 조회
  - get_ontology_relationships: 온톨로지 관계 목록 조회
  - verify_connection: 연결 상태 확인
  - close: 커넥션 풀 종료
  + get_path: 두 노드 간 경로 탐색 (Neo4j에는 없던 추가 기능)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .connection import AgeConnection
from .labels import Labels
from .cypher_compat import (
    build_properties_clause,
    escape_cypher_value,
    parse_agtype,
)


class AgeGraphRepository:
    """Apache AGE 온톨로지 그래프 저장소.

    사용법::

        repo = AgeGraphRepository(conn)
        await repo.sync_ontology_schema(schema_dict)
        nodes = await repo.get_ontology_nodes()
    """

    def __init__(self, conn: AgeConnection):
        self._conn = conn

    # ------------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------------

    async def verify_connection(self) -> bool:
        return await self._conn.verify_connection()

    async def close(self) -> None:
        await self._conn.close()

    # ------------------------------------------------------------------
    # 스키마 동기화 (Neo4jService.sync_ontology_schema 대응)
    # ------------------------------------------------------------------

    async def sync_ontology_schema(self, schema: Dict[str, Any]) -> None:
        """온톨로지 스키마를 AGE 그래프에 동기화.

        Args:
            schema: OntologySchema를 dict로 변환한 것 (.model_dump() 결과).
                    최소 필수 키: id, name, nodes, relationships
        """
        await self._ensure_labels(schema)

        await self._delete_existing_ontology_nodes()

        await self._upsert_schema_meta(schema)

        node_age_ids: Dict[str, int] = {}
        for node in schema.get("nodes", []):
            age_id = await self._create_node(schema["id"], node)
            if age_id is not None:
                node_age_ids[node["id"]] = age_id

        for rel in schema.get("relationships", []):
            await self._create_relationship(rel, node_age_ids)

    async def _ensure_labels(self, schema: Dict[str, Any]) -> None:
        """필요한 vertex/edge label을 미리 생성."""
        vlabels = {Labels.SCHEMA, Labels.NODE}
        elabels = {"HAS_NODE"}

        for node in schema.get("nodes", []):
            lbl = node.get("label")
            if lbl:
                vlabels.add(lbl)

        for rel in schema.get("relationships", []):
            rtype = rel.get("type")
            if rtype:
                elabels.add(rtype)

        for vl in vlabels:
            await self._conn.ensure_vlabel(vl)
        for el in elabels:
            await self._conn.ensure_elabel(el)

    async def _delete_existing_ontology_nodes(self) -> None:
        """기존 OntologyNode 라벨 노드와 연결된 엣지를 모두 삭제."""
        try:
            await self._conn.execute_cypher(
                f"MATCH (n:{Labels.NODE}) DETACH DELETE n"
            )
        except Exception:
            pass

    async def _upsert_schema_meta(self, schema: Dict[str, Any]) -> None:
        """스키마 메타데이터 노드 생성/갱신.

        AGE에서 MERGE 지원이 제한적이므로 MATCH 후 없으면 CREATE.
        """
        sid = escape_cypher_value(schema["id"])

        rows = await self._conn.execute_cypher(
            f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) RETURN id(s)"
        )
        now = datetime.now(timezone.utc).isoformat()

        if rows:
            set_parts = (
                f"s.name = {escape_cypher_value(schema.get('name', ''))}, "
                f"s.description = {escape_cypher_value(schema.get('description', ''))}, "
                f"s.domain = {escape_cypher_value(schema.get('domain', ''))}, "
                f"s.version = {escape_cypher_value(schema.get('version', 1))}, "
                f"s.updatedAt = {escape_cypher_value(now)}"
            )
            await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) SET {set_parts} RETURN id(s)"
            )
        else:
            props = {
                "id": schema["id"],
                "name": schema.get("name", ""),
                "description": schema.get("description", ""),
                "domain": schema.get("domain", ""),
                "version": schema.get("version", 1),
                "updatedAt": now,
            }
            clause = build_properties_clause(props)
            await self._conn.execute_cypher(
                f"CREATE (s:{Labels.SCHEMA} {clause}) RETURN id(s)"
            )

    async def _create_node(
        self,
        schema_id: str,
        node: Dict[str, Any],
    ) -> Optional[int]:
        """온톨로지 노드 생성 + HAS_NODE 관계 연결.

        Returns:
            AGE 내부 vertex id (int) 또는 실패 시 None.
        """
        properties_meta = ""
        if node.get("properties"):
            prop_dict = {}
            for p in node["properties"]:
                if isinstance(p, dict):
                    prop_dict[p["name"]] = {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                        "required": p.get("required", False),
                    }
            properties_meta = json.dumps(prop_dict, ensure_ascii=False)

        label = node.get("label", Labels.NODE)
        props = {
            "id": node["id"],
            "name": node.get("name", ""),
            "description": node.get("description", ""),
            "dataSource": node.get("dataSource", ""),
            "dataSourceSchema": (
                json.dumps(node["dataSourceSchema"], ensure_ascii=False)
                if isinstance(node.get("dataSourceSchema"), (dict, list))
                else str(node.get("dataSourceSchema", ""))
            ),
            "materializedView": node.get("materializedView", ""),
            "properties": properties_meta,
        }

        optional_fields = [
            "layer", "unit", "formula", "targetValue", "thresholds",
            "timeColumn", "timeGranularity", "aggregationMethod",
        ]
        for f in optional_fields:
            val = node.get(f)
            if val is not None:
                if isinstance(val, (dict, list)):
                    props[f] = json.dumps(val, ensure_ascii=False)
                else:
                    props[f] = val

        clause = build_properties_clause(props)
        try:
            row = await self._conn.execute_cypher(
                f"CREATE (n:{label} {clause}) RETURN id(n)"
            )
            if not row:
                return None
            age_id = parse_agtype(row[0][0])

            sid = escape_cypher_value(schema_id)
            await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}), (n) "
                f"WHERE id(n) = {age_id} "
                f"CREATE (s)-[:HAS_NODE]->(n) RETURN 1"
            )
            return int(age_id)
        except Exception:
            return None

    async def _create_relationship(
        self,
        rel: Dict[str, Any],
        node_age_ids: Dict[str, int],
    ) -> bool:
        """온톨로지 관계 생성.

        Returns:
            성공 여부.
        """
        source_age = node_age_ids.get(rel["source"])
        target_age = node_age_ids.get(rel["target"])
        if source_age is None or target_age is None:
            return False

        rtype = rel.get("type", "RELATED_TO")
        props: Dict[str, Any] = {"id": rel.get("id", "")}
        if rel.get("description"):
            props["description"] = rel["description"]
        for f in ("weight", "lag", "confidence", "sourceLayer", "targetLayer",
                   "fromField", "toField"):
            val = rel.get(f)
            if val is not None:
                props[f] = val

        clause = build_properties_clause(props)
        try:
            await self._conn.execute_cypher(
                f"MATCH (a), (b) "
                f"WHERE id(a) = {source_age} AND id(b) = {target_age} "
                f"CREATE (a)-[r:{rtype} {clause}]->(b) RETURN 1"
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 조회 (Neo4jService.get_ontology_nodes / get_ontology_relationships 대응)
    # ------------------------------------------------------------------

    async def get_ontology_nodes(self) -> List[Dict[str, Any]]:
        """온톨로지 노드 목록 조회.

        Returns:
            [{"id": ..., "name": ..., "labels": [...], "description": ..., "dataSource": ...}, ...]
        """
        cypher = (
            f"MATCH (n:{Labels.NODE}) "
            f"RETURN n"
        )
        rows = await self._conn.execute_cypher(cypher)
        results = []
        for row in rows:
            vertex = parse_agtype(row[0])
            if isinstance(vertex, dict):
                props = vertex.get("properties", vertex)
                results.append({
                    "id": props.get("id"),
                    "name": props.get("name"),
                    "labels": [Labels.NODE, props.get("label", "")],
                    "description": props.get("description"),
                    "dataSource": props.get("dataSource"),
                })
            else:
                results.append({"raw": vertex})
        return results

    async def get_ontology_relationships(self) -> List[Dict[str, Any]]:
        """온톨로지 관계 목록 조회 (HAS_NODE 제외).

        Returns:
            [{"id": ..., "source": ..., "target": ..., "type": ..., "description": ...}, ...]
        """
        cypher = (
            f"MATCH (src:{Labels.NODE})-[r]->(tgt:{Labels.NODE}) "
            f"RETURN r"
        )
        rows = await self._conn.execute_cypher(cypher)
        results = []
        for row in rows:
            edge = parse_agtype(row[0])
            if isinstance(edge, dict):
                props = edge.get("properties", edge)
                etype = edge.get("label", props.get("type", ""))
                if etype == "HAS_NODE":
                    continue
                results.append({
                    "id": props.get("id"),
                    "source": props.get("source"),
                    "target": props.get("target"),
                    "type": etype,
                    "description": props.get("description"),
                })
        return results

    # ------------------------------------------------------------------
    # 추가 기능: 경로 탐색
    # ------------------------------------------------------------------

    async def get_path(
        self,
        start_node_id: str,
        end_node_id: str,
        max_depth: int = 5,
    ) -> List[Dict[str, Any]]:
        """두 노드 사이의 최단 경로 탐색.

        AGE에서 가변길이 경로 성능이 제한적이므로
        depth를 1씩 증가시키며 탐색한다.

        Args:
            start_node_id: 시작 노드의 id 속성값.
            end_node_id: 도착 노드의 id 속성값.
            max_depth: 최대 탐색 깊이 (기본 5).

        Returns:
            경로의 각 홉을 나타내는 dict 리스트.
        """
        sid = escape_cypher_value(start_node_id)
        eid = escape_cypher_value(end_node_id)

        for depth in range(1, max_depth + 1):
            intermediate = "".join(f"-->(m{i})-->" for i in range(depth - 1))
            if depth == 1:
                pattern = f"(a)-[r]->(b)"
            else:
                hops = []
                for i in range(depth):
                    if i == depth - 1:
                        hops.append(f"-[r{i}]->(b)")
                    else:
                        hops.append(f"-[r{i}]->(m{i})")
                pattern = "(a)" + "".join(hops)

            cypher = (
                f"MATCH {pattern} "
                f"WHERE a.id = {sid} AND b.id = {eid} "
                f"RETURN a"
            )
            try:
                rows = await self._conn.execute_cypher(cypher)
                if rows:
                    return [{"depth": depth, "found": True,
                             "start": start_node_id, "end": end_node_id}]
            except Exception:
                continue

        return []

    # ------------------------------------------------------------------
    # 단일 노드/관계 CRUD
    # ------------------------------------------------------------------

    async def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """id 속성으로 단일 노드 조회."""
        nid = escape_cypher_value(node_id)
        rows = await self._conn.execute_cypher(
            f"MATCH (n {{id: {nid}}}) RETURN n"
        )
        if not rows:
            return None
        return parse_agtype(rows[0][0])

    async def delete_node_by_id(self, node_id: str) -> bool:
        """id 속성으로 노드 삭제 (연결 엣지 포함)."""
        nid = escape_cypher_value(node_id)
        try:
            await self._conn.execute_cypher(
                f"MATCH (n {{id: {nid}}}) DETACH DELETE n"
            )
            return True
        except Exception:
            return False

    async def update_node_properties(
        self,
        node_id: str,
        properties: Dict[str, Any],
    ) -> bool:
        """노드 속성 갱신."""
        nid = escape_cypher_value(node_id)
        set_parts = ", ".join(
            f"n.{k} = {escape_cypher_value(v)}" for k, v in properties.items()
        )
        try:
            await self._conn.execute_cypher(
                f"MATCH (n {{id: {nid}}}) SET {set_parts} RETURN id(n)"
            )
            return True
        except Exception:
            return False

    async def count_nodes(self, label: Optional[str] = None) -> int:
        """노드 수 카운트."""
        if label:
            cypher = f"MATCH (n:{label}) RETURN count(n)"
        else:
            cypher = "MATCH (n) RETURN count(n)"
        val = await self._conn.execute_cypher_scalar(cypher)
        return int(parse_agtype(val) or 0)

    async def count_relationships(self, rel_type: Optional[str] = None) -> int:
        """관계 수 카운트."""
        if rel_type:
            cypher = f"MATCH ()-[r:{rel_type}]->() RETURN count(r)"
        else:
            cypher = "MATCH ()-[r]->() RETURN count(r)"
        val = await self._conn.execute_cypher_scalar(cypher)
        return int(parse_agtype(val) or 0)
