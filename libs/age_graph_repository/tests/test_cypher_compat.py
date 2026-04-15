"""cypher_compat 유틸리티 단위 테스트 (외부 의존성 없음)."""

import pytest

from age_graph_repository.cypher_compat import (
    escape_cypher_value,
    build_properties_clause,
    neo4j_to_age_cypher,
    build_merge_as_upsert,
    parse_agtype,
)


class TestEscapeCypherValue:
    def test_none(self):
        assert escape_cypher_value(None) == "null"

    def test_bool_true(self):
        assert escape_cypher_value(True) == "true"

    def test_bool_false(self):
        assert escape_cypher_value(False) == "false"

    def test_int(self):
        assert escape_cypher_value(42) == "42"

    def test_float(self):
        assert escape_cypher_value(3.14) == "3.14"

    def test_string(self):
        assert escape_cypher_value("hello") == "'hello'"

    def test_string_with_quotes(self):
        result = escape_cypher_value("it's a test")
        assert result == "'it\\'s a test'"

    def test_string_with_backslash(self):
        result = escape_cypher_value("path\\to\\file")
        assert "\\\\" in result

    def test_dict(self):
        result = escape_cypher_value({"a": 1})
        assert result.startswith("'")
        assert "a" in result

    def test_list(self):
        result = escape_cypher_value([1, "two", True])
        assert result == "[1, 'two', true]"

    def test_korean_string(self):
        result = escape_cypher_value("정수장 운영")
        assert "정수장 운영" in result


class TestBuildPropertiesClause:
    def test_empty(self):
        assert build_properties_clause({}) == ""

    def test_single_prop(self):
        result = build_properties_clause({"name": "test"})
        assert result == "{name: 'test'}"

    def test_multiple_props(self):
        result = build_properties_clause({"id": "a1", "name": "KPI", "value": 42})
        assert "id: 'a1'" in result
        assert "name: 'KPI'" in result
        assert "value: 42" in result

    def test_special_chars_in_key(self):
        result = build_properties_clause({"data-source": "table_a"})
        assert "data_source" in result


class TestNeo4jToAgeCypher:
    def test_labels_to_label(self):
        cypher = "RETURN labels(n) AS lbl"
        result = neo4j_to_age_cypher(cypher)
        assert "label(n)" in result
        assert "labels(" not in result

    def test_datetime_replacement(self):
        cypher = "SET n.updatedAt = datetime()"
        result = neo4j_to_age_cypher(cypher)
        assert "'now'" in result
        assert "datetime()" not in result

    def test_no_change_needed(self):
        cypher = "MATCH (n:KPI) RETURN n.name"
        assert neo4j_to_age_cypher(cypher) == cypher


class TestBuildMergeAsUpsert:
    def test_produces_two_queries(self):
        result = build_merge_as_upsert(
            "KPI",
            match_props={"id": "kpi_1"},
            set_props={"name": "My KPI"},
        )
        parts = result.split("---SEPARATOR---")
        assert len(parts) == 2
        assert "MATCH" in parts[0]
        assert "CREATE" in parts[1]

    def test_match_query_contains_where_props(self):
        result = build_merge_as_upsert(
            "Measure",
            match_props={"id": "m_1"},
            set_props={"unit": "kg"},
        )
        match_part = result.split("---SEPARATOR---")[0]
        assert "'m_1'" in match_part

    def test_create_query_has_all_props(self):
        result = build_merge_as_upsert(
            "Measure",
            match_props={"id": "m_1"},
            set_props={"unit": "kg", "value": 100},
        )
        create_part = result.split("---SEPARATOR---")[1]
        assert "'m_1'" in create_part
        assert "'kg'" in create_part
        assert "100" in create_part


class TestParseAgtype:
    def test_none(self):
        assert parse_agtype(None) is None

    def test_integer_string(self):
        assert parse_agtype("42") == 42

    def test_float_string(self):
        assert parse_agtype("3.14") == 3.14

    def test_quoted_string(self):
        result = parse_agtype('"hello world"')
        assert result == "hello world"

    def test_json_object(self):
        result = parse_agtype('{"id": 1, "name": "test"}')
        assert isinstance(result, dict)
        assert result["id"] == 1

    def test_json_array(self):
        result = parse_agtype('[1, 2, 3]')
        assert isinstance(result, list)
        assert len(result) == 3

    def test_plain_text(self):
        result = parse_agtype("just text")
        assert result == "just text"
