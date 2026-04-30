# K-AIR-GraphDB-t2s — Text2SQL 검증 전용 AGE + pgvector 인스턴스

## 목적
- 기존 `kair-graphdb`(포트 15432)는 운영·Argus 투영 경로용 **원본 유지**
- 본 인스턴스는 **Neo4j → AGE 이관 검증 및 T2SQL 회귀 테스트** 전용
- REPORT v5 §0-4·§6 "GraphDB = T2SQL 메타 원본" 방향성과 정합

## 구성
- Base: `postgres:16` + **Apache AGE 1.5.0** + **pgvector 0.7.4** (Dockerfile·init은 `../K-AIR-GraphDB/` 재사용)
- DB: `kair_graphdb_t2s` / User: `kair` / Password: `kair_pass`
- 포트: **15433:5432** (기존 kair-graphdb 15432와 비충돌)
- 볼륨: `kair_graphdb_t2s_data` (명시적으로 별도 볼륨 — 기존 인스턴스와 격리)

## 기동
```powershell
cd C:\Users\LSW\Documents\GitHub\K_Water_v1\docker\K-AIR-GraphDB-t2s
docker compose up -d --build
docker compose ps
docker compose logs -f kair-graphdb-t2s
```

## 접속 확인
```powershell
# 외부(호스트)에서
$env:PGPASSWORD = "kair_pass"
psql -h 127.0.0.1 -p 15433 -U kair -d kair_graphdb_t2s -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('age','vector');"

# 또는 컨테이너 내부
docker exec -it kair-graphdb-t2s psql -U kair -d kair_graphdb_t2s -c "LOAD 'age'; SET search_path = ag_catalog, \"$user\", public; SELECT * FROM ag_graph;"
```

## 이관 대상 (본 인스턴스에 적재)
- `ontology_graph` (AGE 그래프) ← Neo4j 전 노드/관계
- `t2s_tables / t2s_columns / t2s_fk_constraints` ← Neo4j `Table/Column/FK_TO`
- `embedding_tables` ← Neo4j `Table.text_to_sql_vector(1536)` + HNSW 인덱스
- `embedding_ontology_nodes` ← Neo4j `OntologySchema / OntologyType / KPI / Measure / Process / Resource / Driver / Model`
- `ontology_schemas` (RDB 메타) ← Neo4j `OntologySchema`

## 다음 단계
- `scripts/migrate_age/migrate_neo4j_to_age.py` — 스냅샷 JSON을 본 인스턴스로 적재
- (대기) `age_graph_api` / `age_meta_api` — 기존 `neo4j_remote_api` / `neo4j_client` 동일 계약으로 재구성
