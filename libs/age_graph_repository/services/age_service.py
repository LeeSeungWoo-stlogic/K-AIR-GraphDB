"""
AgeService — Neo4jService drop-in 대체.

Neo4jService와 동일한 퍼블릭 인터페이스를 제공하되,
내부적으로 AgeConnection(asyncpg)을 사용한다.

변경 포인트:
  - AsyncGraphDatabase.driver() → AgeConnection
  - session.run(cypher, **params) → conn.execute_cypher(age_cypher)
  - MERGE ... SET → MATCH-or-CREATE 분기
  - labels(n) → label(n)
  - 파라미터 바인딩 ($param) → 인라인 값 치환
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..connection import AgeConnection
from ..labels import Labels
from ..cypher_compat import escape_cypher_value, build_properties_clause, parse_agtype

logger = logging.getLogger(__name__)


class AgeService:
    """Apache AGE 데이터베이스 서비스 (Neo4jService 대체)."""

    def __init__(self, conn: AgeConnection):
        self._conn = conn

    @property
    def conn(self) -> AgeConnection:
        return self._conn

    async def verify_connection(self) -> bool:
        return await self._conn.verify_connection()

    async def close(self) -> None:
        await self._conn.close()

    async def sync_ontology_schema(self, schema_dict: Dict[str, Any]) -> None:
        """온톨로지 스키마를 AGE에 동기화.

        Neo4jService.sync_ontology_schema와 동일한 로직을
        AGE Cypher로 변환하여 실행한다.
        """
        schema_id = schema_dict.get("id", "")

        await self._delete_schema_nodes(schema_id)
        await self._upsert_schema_meta(schema_dict)

        node_age_ids: Dict[str, int] = {}
        for node in schema_dict.get("nodes", []):
            age_id = await self._create_node(schema_id, node)
            if age_id is not None:
                node_age_ids[node["id"]] = age_id

        for rel in schema_dict.get("relationships", []):
            await self._create_relationship(schema_id, rel, node_age_ids)

    async def _delete_schema_nodes(self, schema_id: str) -> None:
        sid = escape_cypher_value(schema_id)
        for label in (Labels.TYPE, Labels.NODE):
            try:
                await self._conn.execute_cypher(
                    f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_NODE]->(n:{label}) "
                    f"DETACH DELETE n"
                )
            except Exception:
                pass

    async def _upsert_schema_meta(self, schema: Dict[str, Any]) -> None:
        sid = escape_cypher_value(schema["id"])
        rows = await self._conn.execute_cypher(
            f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) RETURN id(s)"
        )

        if rows:
            sets = ", ".join(
                f"s.{k} = {escape_cypher_value(v)}"
                for k, v in {
                    "name": schema.get("name", ""),
                    "domain": schema.get("domain", ""),
                    "description": schema.get("description", ""),
                    "version": schema.get("version", 1),
                    "updatedAt": schema.get("updatedAt", ""),
                    "createdAt": schema.get("createdAt", ""),
                    "schemaJson": schema.get("schemaJson", ""),
                }.items()
            )
            await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) SET {sets} RETURN id(s)"
            )
        else:
            props = {
                "id": schema["id"],
                "name": schema.get("name", ""),
                "domain": schema.get("domain", ""),
                "description": schema.get("description", ""),
                "version": schema.get("version", 1),
                "updatedAt": schema.get("updatedAt", ""),
                "createdAt": schema.get("createdAt", ""),
                "schemaJson": schema.get("schemaJson", ""),
            }
            clause = build_properties_clause(props)
            await self._conn.ensure_vlabel(Labels.SCHEMA)
            await self._conn.execute_cypher(
                f"CREATE (s:{Labels.SCHEMA} {clause}) RETURN id(s)"
            )

    async def _create_node(self, schema_id: str, node: Dict[str, Any]) -> Optional[int]:
        valid_layers = {"KPI", "Measure", "Driver", "Process", "Resource"}
        layer_label = node.get("label", "")
        label = Labels.TYPE

        if layer_label in valid_layers:
            layer_age_label = getattr(Labels, layer_label.upper(), None)
            if layer_age_label:
                await self._conn.ensure_vlabel(layer_age_label)
                label = layer_age_label

        await self._conn.ensure_vlabel(label)
        await self._conn.ensure_elabel("HAS_NODE")

        ds_schema = node.get("dataSourceSchema", "")
        if isinstance(ds_schema, (dict, list)):
            ds_schema = json.dumps(ds_schema, ensure_ascii=False)

        props = {
            "id": node["id"],
            "name": node.get("name", ""),
            "layer": node.get("label", ""),
            "description": node.get("description", ""),
            "dataSource": node.get("dataSource", ""),
            "dataSourceSchema": str(ds_schema),
        }

        for f in ("unit", "targetValue", "timeColumn", "timeGranularity",
                   "aggregationMethod", "materializedView", "bpmnXml"):
            val = node.get(f)
            if val is not None:
                props[f] = val

        clause = build_properties_clause(props)
        try:
            row = await self._conn.execute_cypher(
                f"CREATE (n:{label} {clause}) RETURN id(n)"
            )
            if not row:
                return None
            age_id = int(parse_agtype(row[0][0]))

            sid = escape_cypher_value(schema_id)
            await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}), (n) "
                f"WHERE id(n) = {age_id} "
                f"CREATE (s)-[:HAS_NODE]->(n) RETURN 1"
            )
            return age_id
        except Exception as e:
            logger.warning(f"노드 생성 실패 ({node.get('id')}): {e}")
            return None

    async def _create_relationship(
        self, schema_id: str, rel: Dict[str, Any], node_age_ids: Dict[str, int]
    ) -> bool:
        src_age = node_age_ids.get(rel.get("source", ""))
        tgt_age = node_age_ids.get(rel.get("target", ""))
        if src_age is None or tgt_age is None:
            return False

        rtype = "EFFECTS"
        await self._conn.ensure_elabel(rtype)

        props = {
            "id": rel.get("id", ""),
            "relationType": rel.get("type", ""),
            "description": rel.get("description", ""),
        }
        clause = build_properties_clause(props)
        try:
            await self._conn.execute_cypher(
                f"MATCH (a), (b) WHERE id(a) = {src_age} AND id(b) = {tgt_age} "
                f"CREATE (a)-[r:{rtype} {clause}]->(b) RETURN 1"
            )
            return True
        except Exception as e:
            logger.warning(f"관계 생성 실패: {e}")
            return False

    async def get_ontology_nodes(self) -> List[Dict[str, Any]]:
        rows = await self._conn.execute_cypher(
            f"MATCH (n:{Labels.NODE}) "
            f"RETURN n.id, n.name, label(n), "
            f"n.description, n.dataSource",
            return_cols="(id agtype, name agtype, lbl agtype, node_desc agtype, ds agtype)",
        )
        return [
            {
                "id": parse_agtype(r[0]),
                "name": parse_agtype(r[1]) if len(r) > 1 else None,
                "labels": [parse_agtype(r[2])] if len(r) > 2 else [],
                "description": parse_agtype(r[3]) if len(r) > 3 else None,
                "dataSource": parse_agtype(r[4]) if len(r) > 4 else None,
            }
            for r in rows
        ]

    async def get_ontology_relationships(self) -> List[Dict[str, Any]]:
        rows = await self._conn.execute_cypher(
            f"MATCH (src:{Labels.NODE})-[r]->(tgt:{Labels.NODE}) "
            f"RETURN r.id, src.id, tgt.id, "
            f"type(r), r.description",
            return_cols="(id agtype, source agtype, target agtype, rtype agtype, rel_desc agtype)",
        )
        results = []
        for r in rows:
            rtype = parse_agtype(r[3]) if len(r) > 3 else ""
            if rtype == "HAS_NODE":
                continue
            results.append({
                "id": parse_agtype(r[0]),
                "source": parse_agtype(r[1]) if len(r) > 1 else None,
                "target": parse_agtype(r[2]) if len(r) > 2 else None,
                "type": rtype,
                "description": parse_agtype(r[4]) if len(r) > 4 else None,
            })
        return results
