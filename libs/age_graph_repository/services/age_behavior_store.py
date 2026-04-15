"""
AgeBehaviorStore — BehaviorStore (schema_store_behavior.py) AGE 전환.

Neo4j Cypher 변환:
  - :OntologyBehavior:Model 멀티레이블 → 단일 :Ontology_OntologyBehavior + behaviorType 속성
  - MERGE → MATCH-or-CREATE
  - collect(DISTINCT {...}) → 별도 쿼리 후 Python 합산
  - $param → 인라인 값
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from ..connection import AgeConnection
from ..labels import Labels
from ..cypher_compat import escape_cypher_value, build_properties_clause, parse_agtype
from .age_guard import requires_age

logger = logging.getLogger(__name__)


class AgeBehaviorStore:
    """행동 모델 CRUD 저장소 (AGE)."""

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
    async def save_behavior_node(self, schema_id: str, behavior) -> bool:
        """Behavior 노드 생성/갱신 + HAS_BEHAVIOR 관계."""
        conn = self._conn
        bid = escape_cypher_value(behavior.id)
        sid = escape_cypher_value(schema_id)

        await conn.ensure_vlabel(Labels.BEHAVIOR)
        await conn.ensure_elabel("HAS_BEHAVIOR")

        existing = await conn.execute_cypher(
            f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
            f"(m:{Labels.BEHAVIOR} {{id: {bid}}}) RETURN id(m)"
        )

        props = {
            "id": behavior.id,
            "name": behavior.name,
            "behaviorType": behavior.behaviorType,
            "description": behavior.description or "",
            "mindsdbModel": behavior.mindsdbModel or "",
            "modelType": behavior.modelType or "",
            "status": behavior.status,
            "version": behavior.version,
            "featureViewSQL": behavior.featureViewSQL or "",
            "metrics": behavior.metrics or "{}",
            "trainDataRows": behavior.trainDataRows or 0,
            "validationSplit": behavior.validationSplit or "",
        }

        try:
            if existing:
                age_id = int(parse_agtype(existing[0][0]))
                for rel_type in ("READS_FIELD", "PREDICTS_FIELD"):
                    try:
                        await conn.ensure_elabel(rel_type)
                        await conn.execute_cypher(
                            f"MATCH ()-[r:{rel_type}]->() "
                            f"WHERE id(r) IN ["
                            f"  x IN [(m)-[rel:{rel_type}]->() WHERE id(m) = {age_id} | id(rel)]"
                            f"] DELETE r"
                        )
                    except Exception:
                        pass

                set_parts = ", ".join(
                    f"m.{k} = {escape_cypher_value(v)}" for k, v in props.items()
                    if k != "id"
                )
                await conn.execute_cypher(
                    f"MATCH (m) WHERE id(m) = {age_id} SET {set_parts} RETURN id(m)"
                )
            else:
                clause = build_properties_clause(props)
                row = await conn.execute_cypher(
                    f"CREATE (m:{Labels.BEHAVIOR} {clause}) RETURN id(m)"
                )
                if not row:
                    return False
                age_id = int(parse_agtype(row[0][0]))

                await conn.execute_cypher(
                    f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}}), (m) "
                    f"WHERE id(m) = {age_id} "
                    f"CREATE (s)-[:HAS_BEHAVIOR]->(m) RETURN 1"
                )
            return True
        except Exception as e:
            logger.error(f"save_behavior_node 실패: {e}")
            return False

    @requires_age(default_return=0)
    async def save_model_field_links(self, links) -> int:
        """READS_FIELD / PREDICTS_FIELD 관계 생성."""
        conn = self._conn
        created = 0
        for link in links:
            try:
                src_id = escape_cypher_value(link.sourceNodeId)
                tgt_id = escape_cypher_value(link.targetNodeId)

                if link.linkType == "READS_FIELD":
                    await conn.ensure_elabel("READS_FIELD")
                    props = {
                        "id": link.id,
                        "field": link.field,
                        "lag": link.lag or 0,
                        "featureName": link.featureName or link.field,
                        "importance": link.importance or 0.0,
                        "correlationScore": link.correlationScore or 0.0,
                        "grangerPValue": link.grangerPValue or 1.0,
                    }
                    clause = build_properties_clause(props)
                    await conn.execute_cypher(
                        f"MATCH (src:{Labels.TYPE} {{id: {src_id}}}), "
                        f"(m:{Labels.BEHAVIOR} {{id: {tgt_id}}}) "
                        f"CREATE (src)-[:READS_FIELD {clause}]->(m) RETURN 1"
                    )
                elif link.linkType == "PREDICTS_FIELD":
                    await conn.ensure_elabel("PREDICTS_FIELD")
                    props = {
                        "id": link.id,
                        "field": link.field,
                        "confidence": link.confidence or 0.0,
                    }
                    clause = build_properties_clause(props)
                    await conn.execute_cypher(
                        f"MATCH (m:{Labels.BEHAVIOR} {{id: {src_id}}}), "
                        f"(tgt:{Labels.TYPE} {{id: {tgt_id}}}) "
                        f"CREATE (m)-[:PREDICTS_FIELD {clause}]->(tgt) RETURN 1"
                    )
                else:
                    continue
                created += 1
            except Exception as e:
                logger.warning(f"필드 링크 생성 실패 ({link.id}): {e}")
        return created

    @requires_age(default_return=False)
    async def update_model_status(
        self, model_id: str, status: str,
        metrics: Optional[str] = None, trained_at: Optional[str] = None,
    ) -> bool:
        conn = self._conn
        mid = escape_cypher_value(model_id)
        sets = [f"m.status = {escape_cypher_value(status)}"]
        if metrics is not None:
            sets.append(f"m.metrics = {escape_cypher_value(metrics)}")
        if trained_at is not None:
            sets.append(f"m.trainedAt = {escape_cypher_value(trained_at)}")

        try:
            rows = await conn.execute_cypher(
                f"MATCH (m:{Labels.BEHAVIOR} {{id: {mid}}}) "
                f"SET {', '.join(sets)} RETURN id(m)"
            )
            return bool(rows)
        except Exception as e:
            logger.error(f"update_model_status 실패: {e}")
            return False

    @requires_age(default_return=list)
    async def get_behaviors_for_schema(self, schema_id: str) -> List[Dict[str, Any]]:
        """스키마의 모든 Behavior 노드 + 필드 링크 조회.

        AGE는 collect(DISTINCT {...})를 지원하지 않으므로 분리 쿼리 사용.
        """
        conn = self._conn
        sid = escape_cypher_value(schema_id)

        models = await conn.execute_cypher(
            f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
            f"(m:{Labels.BEHAVIOR}) RETURN m"
        )

        results = []
        for row in models:
            vertex = parse_agtype(row[0])
            if not isinstance(vertex, dict):
                continue
            props = vertex.get("properties", vertex)
            mid = props.get("id")
            if not mid:
                continue

            mid_esc = escape_cypher_value(mid)

            inputs = []
            try:
                rf_rows = await conn.execute_cypher(
                    f"MATCH (src:{Labels.TYPE})-[r:READS_FIELD]->"
                    f"(m:{Labels.BEHAVIOR} {{id: {mid_esc}}}) "
                    f"RETURN src.id, src.name, r.field, r.lag, "
                    f"r.featureName, r.importance, r.correlationScore",
                    return_cols="(a agtype, b agtype, c agtype, d agtype, e agtype, f agtype, g agtype)",
                )
                for rf in rf_rows:
                    inputs.append({
                        "sourceId": parse_agtype(rf[0]),
                        "sourceName": parse_agtype(rf[1]),
                        "field": parse_agtype(rf[2]),
                        "lag": parse_agtype(rf[3]),
                        "featureName": parse_agtype(rf[4]),
                        "importance": parse_agtype(rf[5]),
                        "correlationScore": parse_agtype(rf[6]),
                    })
            except Exception:
                pass

            outputs = []
            try:
                pf_rows = await conn.execute_cypher(
                    f"MATCH (m:{Labels.BEHAVIOR} {{id: {mid_esc}}})-[r:PREDICTS_FIELD]->"
                    f"(tgt:{Labels.TYPE}) "
                    f"RETURN tgt.id, tgt.name, r.field, r.confidence",
                    return_cols="(a agtype, b agtype, c agtype, d agtype)",
                )
                for pf in pf_rows:
                    outputs.append({
                        "targetId": parse_agtype(pf[0]),
                        "targetName": parse_agtype(pf[1]),
                        "field": parse_agtype(pf[2]),
                        "confidence": parse_agtype(pf[3]),
                    })
            except Exception:
                pass

            results.append({
                "modelId": mid,
                "name": props.get("name"),
                "status": props.get("status"),
                "mindsdbModel": props.get("mindsdbModel"),
                "modelType": props.get("modelType"),
                "metrics": props.get("metrics"),
                "version": props.get("version"),
                "trainedAt": props.get("trainedAt"),
                "description": props.get("description"),
                "inputs": inputs,
                "outputs": outputs,
            })

        return results

    @requires_age(default_return=lambda: {"models": [], "reads": [], "predicts": []})
    async def get_model_graph(self, schema_id: str) -> Dict[str, Any]:
        """시뮬레이션용 모델 DAG 조회."""
        conn = self._conn
        sid = escape_cypher_value(schema_id)

        model_rows = await conn.execute_cypher(
            f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
            f"(m:{Labels.BEHAVIOR}) RETURN m"
        )
        models = []
        for row in model_rows:
            v = parse_agtype(row[0])
            if isinstance(v, dict):
                props = v.get("properties", v)
                models.append({
                    "id": props.get("id"),
                    "name": props.get("name"),
                    "mindsdbModel": props.get("mindsdbModel"),
                    "modelType": props.get("modelType"),
                    "status": props.get("status"),
                    "metrics": props.get("metrics"),
                    "trainedAt": props.get("trainedAt"),
                })

        reads = []
        try:
            rf = await conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
                f"(m:{Labels.BEHAVIOR})<-[r:READS_FIELD]-(src:{Labels.TYPE}) "
                f"RETURN m.id, src.id, src.name, src.dataSource, "
                f"r.field, r.lag, r.featureName",
                return_cols="(a agtype, b agtype, c agtype, d agtype, e agtype, f agtype, g agtype)",
            )
            for row in rf:
                reads.append({
                    "modelId": parse_agtype(row[0]),
                    "sourceNodeId": parse_agtype(row[1]),
                    "sourceName": parse_agtype(row[2]),
                    "dataSource": parse_agtype(row[3]),
                    "field": parse_agtype(row[4]),
                    "lag": parse_agtype(row[5]),
                    "featureName": parse_agtype(row[6]),
                })
        except Exception:
            pass

        predicts = []
        try:
            pf = await conn.execute_cypher(
                f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
                f"(m:{Labels.BEHAVIOR})-[r:PREDICTS_FIELD]->(tgt:{Labels.TYPE}) "
                f"RETURN m.id, tgt.id, tgt.name, tgt.dataSource, "
                f"r.field, r.confidence",
                return_cols="(a agtype, b agtype, c agtype, d agtype, e agtype, f agtype)",
            )
            for row in pf:
                predicts.append({
                    "modelId": parse_agtype(row[0]),
                    "targetNodeId": parse_agtype(row[1]),
                    "targetName": parse_agtype(row[2]),
                    "dataSource": parse_agtype(row[3]),
                    "field": parse_agtype(row[4]),
                    "confidence": parse_agtype(row[5]),
                })
        except Exception:
            pass

        return {"models": models, "reads": reads, "predicts": predicts}

    @requires_age(default_return=False)
    async def delete_behavior(self, model_id: str, schema_id: Optional[str] = None) -> bool:
        conn = self._conn
        mid = escape_cypher_value(model_id)
        try:
            if schema_id:
                sid = escape_cypher_value(schema_id)
                await conn.execute_cypher(
                    f"MATCH (s:{Labels.SCHEMA} {{id: {sid}}})-[:HAS_BEHAVIOR]->"
                    f"(m:{Labels.BEHAVIOR} {{id: {mid}}}) DETACH DELETE m"
                )
            else:
                await conn.execute_cypher(
                    f"MATCH (m:{Labels.BEHAVIOR} {{id: {mid}}}) DETACH DELETE m"
                )
            return True
        except Exception as e:
            logger.error(f"delete_behavior 실패: {e}")
            return False
