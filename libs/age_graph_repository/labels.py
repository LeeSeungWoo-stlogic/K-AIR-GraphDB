"""
AGE vertex/edge label 상수.
K-AIR neo4j_labels.py와 동일한 상수 + AGE 호환 유틸.

AGE 제약: 단일 레이블만 허용, 라벨명은 유효한 SQL 식별자여야 함.
Neo4j의 Ontology_ 접두사를 그대로 유지하되,
멀티레이블(:OntologyNode:KPI)은 단일 레이블 + _labels 속성으로 대체한다.
"""

PREFIX = "Ontology_"


class Labels:
    SCHEMA = f"{PREFIX}OntologySchema"
    TYPE = f"{PREFIX}OntologyType"
    NODE = f"{PREFIX}OntologyNode"
    BEHAVIOR = f"{PREFIX}OntologyBehavior"
    INSTANCE = f"{PREFIX}OntologyInstance"
    SCENARIO = f"{PREFIX}WhatIfScenarioProfile"

    KPI = f"{PREFIX}KPI"
    MEASURE = f"{PREFIX}Measure"
    DRIVER = f"{PREFIX}Driver"
    PROCESS = f"{PREFIX}Process"
    RESOURCE = f"{PREFIX}Resource"

    TABLE = f"{PREFIX}Table"
    COLUMN = f"{PREFIX}Column"
    OBJECT_TYPE = f"{PREFIX}ObjectType"
    BEHAVIOR_NODE = f"{PREFIX}Behavior"

    BUSINESS_CALENDAR = f"{PREFIX}BusinessCalendar"
    NON_BUSINESS_DAY = f"{PREFIX}NonBusinessDay"
    HOLIDAY = f"{PREFIX}Holiday"


class LegacyLabels:
    SCHEMA = "OntologySchema"
    TYPE = "OntologyType"
    NODE = "OntologyNode"
    BEHAVIOR = "OntologyBehavior"
    INSTANCE = "OntologyInstance"
    SCENARIO = "WhatIfScenarioProfile"
    KPI = "KPI"
    MEASURE = "Measure"
    DRIVER = "Driver"
    PROCESS = "Process"
    RESOURCE = "Resource"
    TABLE = "Table"
    COLUMN = "Column"
    OBJECT_TYPE = "ObjectType"
    BEHAVIOR_NODE = "Behavior"
    BUSINESS_CALENDAR = "BusinessCalendar"
    NON_BUSINESS_DAY = "NonBusinessDay"
    HOLIDAY = "Holiday"
