"""
AgeSchemaStore — SchemaStore (schema_store.py) AGE 전환.

Neo4j Cypher → AGE Cypher 변환 포인트:
  - OPTIONAL MATCH → 별도 쿼리 분리
  - MERGE ... SET → MATCH-or-CREATE 패턴
  - $param 바인딩 → 인라인 값 치환
  - labels(n) → label(n)
  - 멀티레이블 → 단일 레이블 + layer 속성
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import uuid

from ..connection import AgeConnection
from ..labels import Labels
from ..cypher_compat import escape_cypher_value, build_properties_clause, parse_agtype
from ..catalog_adapter import CatalogAdapter
from .age_guard import requires_age
from .age_service import AgeService
from .age_behavior_store import AgeBehaviorStore
from .age_scenario_store import AgeScenarioStore

logger = logging.getLogger(__name__)


class AgeSchemaStore:
    """온톨로지 스키마 저장소 (AGE + RDB 이중 저장).

    SchemaStore와 동일한 인터페이스를 제공한다.
    BehaviorStore, ScenarioStore도 AGE 버전으로 위임한다.
    """

    _instance: Optional["AgeSchemaStore"] = None
    _age: Optional[AgeService] = None
    _conn: Optional[AgeConnection] = None
    _catalog: Optional[CatalogAdapter] = None

    _active_schema: Optional[Dict[str, Any]] = None
    _active_schema_id: Optional[str] = None

    _behavior_store: Optional[AgeBehaviorStore] = None
    _scenario_store: Optional[AgeScenarioStore] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_age_service(self, age: AgeService) -> None:
        """AgeService 주입 — 서브 스토어에도 전달."""
        self._age = age
        self._conn = age.conn
        self._catalog = CatalogAdapter(age.conn)
        self._behavior_store = AgeBehaviorStore(age_provider=lambda: self._age)
        self._scenario_store = AgeScenarioStore(age_provider=lambda: self._age)

    def _ensure_behavior_store(self) -> AgeBehaviorStore:
        if self._behavior_store is None:
            self._behavior_store = AgeBehaviorStore(age_provider=lambda: self._age)
        return self._behavior_store

    def _ensure_scenario_store(self) -> AgeScenarioStore:
        if self._scenario_store is None:
            self._scenario_store = AgeScenarioStore(age_provider=lambda: self._age)
        return self._scenario_store

    # ================================================================
    # 스키마 목록 관리
    # ================================================================

    @requires_age(default_return=list)
    async def list_schemas(self) -> List[Dict[str, Any]]:
        """저장된 모든 스키마 목록 조회."""
        sid_label = Labels.SCHEMA

        rows = await self._conn.execute_cypher(
            f"MATCH (s:{sid_label}) "
            f"RETURN s"
        )

        schemas = []
        for row in rows:
            vertex = parse_agtype(row[0])
            if not isinstance(vertex, dict):
                continue
            props = vertex.get("properties", vertex)

            node_count = 0
            s_id = props.get("id")
            if s_id:
                try:
                    cnt_rows = await self._conn.execute_cypher(
                        f"MATCH (s:{sid_label} {{id: {escape_cypher_value(s_id)}}})"
                        f"-[:HAS_NODE]->(n) RETURN count(n)"
                    )
                    if cnt_rows:
                        node_count = int(parse_agtype(cnt_rows[0][0]) or 0)
                except Exception:
                    pass

            schemas.append({
                "id": s_id,
                "name": props.get("name"),
                "domain": props.get("domain"),
                "description": props.get("description"),
                "createdAt": props.get("createdAt"),
                "updatedAt": props.get("updatedAt"),
                "version": props.get("version"),
                "nodeCount": node_count,
                "hasSchemaJson": bool(props.get("schemaJson")),
            })

        return schemas

    async def get_schema(self, schema_id: Optional[str] = None):
        """스키마 조회."""
        if not schema_id:
            return self._active_schema

        if schema_id == self._active_schema_id and self._active_schema:
            return self._active_schema

        if not self._conn:
            return None

        sid = escape_cypher_value(schema_id)
        try:
            rows = await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) RETURN s"
            )
            if not rows:
                return None

            vertex = parse_agtype(rows[0][0])
            if not isinstance(vertex, dict):
                return None

            props = vertex.get("properties", vertex)
            schema_json = props.get("schemaJson")
            if not schema_json:
                return None

            return json.loads(schema_json)
        except Exception as e:
            logger.error(f"스키마 조회 실패 ({schema_id}): {e}")
            return None

    async def save_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """스키마 저장 (AGE 그래프 + RDB 이중 저장)."""
        now = datetime.now(timezone.utc).isoformat()

        if not schema_dict.get("id"):
            schema_dict["id"] = str(uuid.uuid4())
            schema_dict["createdAt"] = now
            schema_dict["version"] = 1

        schema_dict["updatedAt"] = now
        schema_dict["schemaJson"] = json.dumps(schema_dict, ensure_ascii=False, default=str)

        if self._age:
            await self._age.sync_ontology_schema(schema_dict)

            sid = escape_cypher_value(schema_dict["id"])
            sj = escape_cypher_value(schema_dict["schemaJson"])
            try:
                await self._conn.execute_cypher(
                    f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) "
                    f"SET s.schemaJson = {sj} RETURN id(s)"
                )
            except Exception:
                pass

        if self._catalog:
            try:
                await self._catalog.sync_schema_to_rdb(schema_dict)
            except Exception as e:
                logger.warning(f"RDB 스키마 동기화 실패: {e}")

        self._active_schema = schema_dict
        self._active_schema_id = schema_dict["id"]
        return schema_dict

    @requires_age(default_return=False)
    async def delete_schema(self, schema_id: Optional[str] = None) -> bool:
        """스키마 삭제 (AGE 그래프)."""
        target_id = schema_id or self._active_schema_id
        if not target_id:
            return False

        sid = escape_cypher_value(target_id)
        try:
            for label in (Labels.TYPE, Labels.NODE, Labels.BEHAVIOR):
                try:
                    await self._conn.execute_cypher(
                        f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[]->(n:{label}) "
                        f"DETACH DELETE n"
                    )
                except Exception:
                    pass

            await self._conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}) DETACH DELETE s"
            )
        except Exception as e:
            logger.error(f"스키마 삭제 실패: {e}")
            return False

        if target_id == self._active_schema_id:
            self._active_schema = None
            self._active_schema_id = None

        return True

    async def set_active_schema(self, schema_id: str):
        schema = await self.get_schema(schema_id)
        if schema:
            self._active_schema = schema
            self._active_schema_id = schema_id
        return schema

    async def update_node(self, node_id: str, updates: dict) -> bool:
        if not self._active_schema:
            return False

        nodes = self._active_schema.get("nodes", [])
        for i, node in enumerate(nodes):
            if isinstance(node, dict) and node.get("id") == node_id:
                nodes[i].update(updates)
                self._active_schema["updatedAt"] = datetime.now(timezone.utc).isoformat()
                await self.save_schema(self._active_schema)
                return True
        return False

    async def get_active_schema_id(self) -> Optional[str]:
        return self._active_schema_id

    # ================================================================
    # Behavior 위임
    # ================================================================

    async def save_behavior_node(self, schema_id, behavior):
        return await self._ensure_behavior_store().save_behavior_node(schema_id, behavior)

    async def save_model_field_links(self, links):
        return await self._ensure_behavior_store().save_model_field_links(links)

    async def update_model_status(self, model_id, status, metrics=None, trained_at=None):
        return await self._ensure_behavior_store().update_model_status(
            model_id, status, metrics, trained_at
        )

    async def get_behaviors_for_schema(self, schema_id):
        return await self._ensure_behavior_store().get_behaviors_for_schema(schema_id)

    async def get_model_graph(self, schema_id):
        return await self._ensure_behavior_store().get_model_graph(schema_id)

    async def delete_behavior(self, model_id, schema_id=None):
        return await self._ensure_behavior_store().delete_behavior(model_id, schema_id)

    # ================================================================
    # Scenario 위임
    # ================================================================

    async def save_scenario(self, scenario):
        return await self._ensure_scenario_store().save_scenario(scenario)

    async def list_scenarios(self, schema_id):
        return await self._ensure_scenario_store().list_scenarios(schema_id)

    async def get_scenario(self, scenario_id):
        return await self._ensure_scenario_store().get_scenario(scenario_id)

    async def delete_scenario(self, scenario_id):
        return await self._ensure_scenario_store().delete_scenario(scenario_id)

    async def list_all_scenarios(self):
        return await self._ensure_scenario_store().list_all_scenarios()
