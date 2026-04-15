"""
AgeScenarioStore — ScenarioStore (schema_store_scenario.py) AGE 전환.

Neo4j Cypher 변환:
  - MERGE (sc:Scenario {id: $id}) SET ... → MATCH-or-CREATE
  - MERGE (s)-[:HAS_SCENARIO]->(sc) → 별도 CREATE
  - $param → 인라인 값
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime, timezone

from ..connection import AgeConnection
from ..labels import Labels
from ..cypher_compat import escape_cypher_value, build_properties_clause, parse_agtype
from .age_guard import requires_age

logger = logging.getLogger(__name__)


def _deserialize_json_fields(records: List[Dict], json_keys: List[str]) -> List[Dict]:
    result = []
    for record in records:
        r = dict(record)
        for key in json_keys:
            val = r.get(key)
            if isinstance(val, str):
                try:
                    r[key] = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    r[key] = []
        result.append(r)
    return result


class AgeScenarioStore:
    """What-If 시나리오 CRUD 저장소 (AGE)."""

    def __init__(self, age_provider: Optional[Callable] = None):
        self._age_provider = age_provider

    @property
    def _age(self):
        if callable(self._age_provider):
            return self._age_provider()
        return self._age_provider

    @property
    def _conn(self) -> Optional[AgeConnection]:
        age = self._age
        return age.conn if age else None

    @requires_age(default_return=False)
    async def save_scenario(self, scenario) -> bool:
        """시나리오 노드 저장 (MATCH-or-CREATE)."""
        conn = self._conn
        await conn.ensure_vlabel(Labels.SCENARIO)
        await conn.ensure_elabel("HAS_SCENARIO")

        sc_id = escape_cypher_value(scenario.id)
        sid = escape_cypher_value(scenario.schemaId)
        now = datetime.now(timezone.utc).isoformat()

        props = {
            "id": scenario.id,
            "name": scenario.name,
            "description": scenario.description or "",
            "schemaId": scenario.schemaId,
            "interventions": json.dumps(scenario.interventions, ensure_ascii=False),
            "results": json.dumps(scenario.results, ensure_ascii=False) if scenario.results else "{}",
            "traces": json.dumps(scenario.traces, ensure_ascii=False) if scenario.traces else "[]",
            "outputFields": json.dumps(scenario.outputFields, ensure_ascii=False) if scenario.outputFields else "[]",
            "createdAt": scenario.createdAt or now,
            "updatedAt": now,
        }

        try:
            existing = await conn.execute_cypher(
                f"MATCH (sc:{Labels.SCENARIO} {{id: {sc_id}}}) RETURN id(sc)"
            )

            if existing:
                age_id = int(parse_agtype(existing[0][0]))
                set_parts = ", ".join(
                    f"sc.{k} = {escape_cypher_value(v)}" for k, v in props.items()
                    if k != "id"
                )
                await conn.execute_cypher(
                    f"MATCH (sc) WHERE id(sc) = {age_id} SET {set_parts} RETURN id(sc)"
                )
            else:
                clause = build_properties_clause(props)
                row = await conn.execute_cypher(
                    f"CREATE (sc:{Labels.SCENARIO} {clause}) RETURN id(sc)"
                )
                if not row:
                    return False
                age_id = int(parse_agtype(row[0][0]))

                await conn.execute_cypher(
                    f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}), (sc) "
                    f"WHERE id(sc) = {age_id} "
                    f"CREATE (s)-[:HAS_SCENARIO]->(sc) RETURN 1"
                )
            return True
        except Exception as e:
            logger.error(f"save_scenario 실패: {e}")
            return False

    @requires_age(default_return=list)
    async def list_scenarios(self, schema_id: str) -> List[Dict[str, Any]]:
        conn = self._conn
        sid = escape_cypher_value(schema_id)
        try:
            rows = await conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_SCENARIO]->"
                f"(sc:{Labels.SCENARIO}) RETURN sc"
            )
            records = []
            for row in rows:
                v = parse_agtype(row[0])
                if isinstance(v, dict):
                    props = v.get("properties", v)
                    records.append({
                        "id": props.get("id"),
                        "name": props.get("name"),
                        "description": props.get("description"),
                        "schemaId": props.get("schemaId"),
                        "interventions": props.get("interventions"),
                        "outputFields": props.get("outputFields"),
                        "createdAt": props.get("createdAt"),
                        "updatedAt": props.get("updatedAt"),
                    })
            return _deserialize_json_fields(records, ["interventions", "outputFields"])
        except Exception as e:
            logger.error(f"list_scenarios 실패: {e}")
            return []

    @requires_age(default_return=None)
    async def get_scenario(self, scenario_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn
        scid = escape_cypher_value(scenario_id)
        try:
            rows = await conn.execute_cypher(
                f"MATCH (sc:{Labels.SCENARIO} {{id: {scid}}}) RETURN sc"
            )
            if not rows:
                return None
            v = parse_agtype(rows[0][0])
            if not isinstance(v, dict):
                return None
            props = v.get("properties", v)
            record = {
                "id": props.get("id"),
                "name": props.get("name"),
                "description": props.get("description"),
                "schemaId": props.get("schemaId"),
                "interventions": props.get("interventions"),
                "results": props.get("results"),
                "traces": props.get("traces"),
                "outputFields": props.get("outputFields"),
                "createdAt": props.get("createdAt"),
                "updatedAt": props.get("updatedAt"),
            }
            deserialized = _deserialize_json_fields(
                [record], ["interventions", "results", "traces", "outputFields"]
            )
            return deserialized[0] if deserialized else None
        except Exception as e:
            logger.error(f"get_scenario 실패: {e}")
            return None

    @requires_age(default_return=False)
    async def delete_scenario(self, scenario_id: str) -> bool:
        conn = self._conn
        scid = escape_cypher_value(scenario_id)
        try:
            await conn.execute_cypher(
                f"MATCH (sc:{Labels.SCENARIO} {{id: {scid}}}) DETACH DELETE sc"
            )
            return True
        except Exception as e:
            logger.error(f"delete_scenario 실패: {e}")
            return False

    @requires_age(default_return=list)
    async def list_all_scenarios(self) -> List[Dict[str, Any]]:
        conn = self._conn
        try:
            rows = await conn.execute_cypher(
                f"MATCH (sc:{Labels.SCENARIO}) RETURN sc"
            )
            records = []
            for row in rows:
                v = parse_agtype(row[0])
                if isinstance(v, dict):
                    props = v.get("properties", v)
                    records.append({
                        "id": props.get("id"),
                        "name": props.get("name"),
                        "description": props.get("description"),
                        "schemaId": props.get("schemaId"),
                        "interventions": props.get("interventions"),
                        "outputFields": props.get("outputFields"),
                        "createdAt": props.get("createdAt"),
                        "updatedAt": props.get("updatedAt"),
                    })
            return _deserialize_json_fields(records, ["interventions", "outputFields"])
        except Exception as e:
            logger.error(f"list_all_scenarios 실패: {e}")
            return []
