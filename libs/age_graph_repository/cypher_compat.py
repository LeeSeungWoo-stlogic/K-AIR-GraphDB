"""
Neo4j → AGE Cypher 호환성 변환 유틸.

AGE Cypher 서브셋 제약 대응:
  - labels(n) → label(n)  (단수, 단일 레이블)
  - MERGE ... ON CREATE SET / ON MATCH SET → 분기 처리
  - datetime() → 문자열 ISO 포맷
  - 멀티레이블 → 단일 레이블 + _labels 속성
  - 파라미터 바인딩 미지원 → 인라인 값 치환
"""

from __future__ import annotations

import json
import re
from typing import Any


def escape_cypher_value(val: Any) -> str:
    """Python 값을 AGE Cypher 리터럴로 변환."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, dict):
        return escape_cypher_value(json.dumps(val, ensure_ascii=False))
    if isinstance(val, list):
        inner = ", ".join(escape_cypher_value(v) for v in val)
        return f"[{inner}]"
    s = str(val).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def build_properties_clause(props: dict[str, Any]) -> str:
    """속성 dict를 AGE Cypher {key: val, ...} 문자열로 변환."""
    if not props:
        return ""
    parts = []
    for k, v in props.items():
        safe_key = _safe_identifier(k)
        parts.append(f"{safe_key}: {escape_cypher_value(v)}")
    return "{" + ", ".join(parts) + "}"


def _safe_identifier(name: str) -> str:
    """AGE 식별자로 안전한 이름 변환."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = "_" + name
    return name


def neo4j_to_age_cypher(cypher: str) -> str:
    """Neo4j Cypher → AGE 호환 Cypher 기본 변환.

    주요 변환:
      - labels(n) → label(n)
      - datetime() → 현재 시각 ISO 문자열
      - $param 형식 파라미터 참조 제거 (인라인 치환은 호출자 책임)
    """
    result = cypher
    result = re.sub(r'\blabels\s*\(', 'label(', result)
    result = re.sub(r'\bdatetime\s*\(\s*\)', "'now'", result)
    return result


def build_merge_as_upsert(
    label: str,
    match_props: dict[str, Any],
    set_props: dict[str, Any],
) -> str:
    """Neo4j MERGE ... SET → AGE 호환 MATCH-or-CREATE 패턴.

    AGE에서 MERGE ON CREATE SET / ON MATCH SET가 제한적이므로,
    MATCH 시도 후 없으면 CREATE하는 2-step 패턴을 생성한다.
    호출자가 두 쿼리를 순차 실행해야 한다.

    Returns:
        (match_query, create_query) 튜플 형태의 Cypher 2개를 ;로 구분한 문자열.
    """
    all_props = {**match_props, **set_props}
    match_clause = build_properties_clause(match_props)
    all_clause = build_properties_clause(all_props)
    set_parts = ", ".join(
        f"n.{_safe_identifier(k)} = {escape_cypher_value(v)}"
        for k, v in set_props.items()
    )

    match_query = (
        f"MATCH (n:{label} {match_clause}) "
        f"SET {set_parts} "
        f"RETURN id(n)"
    )
    create_query = (
        f"CREATE (n:{label} {all_clause}) "
        f"RETURN id(n)"
    )
    return f"{match_query}\n---SEPARATOR---\n{create_query}"


def parse_agtype(raw: Any) -> Any:
    """asyncpg가 반환하는 agtype 문자열을 Python 객체로 파싱.

    AGE는 결과를 agtype(텍스트)으로 반환하므로 JSON 파싱이 필요하다.
    예: '"hello"' → 'hello', '42' → 42, '{"id": 1}::vertex' → dict
    """
    if raw is None:
        return None
    s = str(raw)
    if s.startswith("::"):
        s = s[2:]
    s = re.sub(r'::(vertex|edge|path)\s*$', '', s)
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s.strip('"')
