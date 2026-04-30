# meta_ingest_proto

**Step 1(물리 메타 → `t2s_*` + AGE)** 파이프라인 개요·추출 항목·관계(`HAS_COLUMN`/`FK_TO`) 매핑은 **[`docs/GUIDE_RDBMS_to_온톨로지_파이프라인.md`](../../docs/GUIDE_RDBMS_to_온톨로지_파이프라인.md)** 를 참고한다.

PostgreSQL 한 스키마의 메타(`information_schema` + `pg_constraint` FK)를 읽어 **K-AIR GraphDB**에 적재하는 프로토타입.

구현은 **`meta_ingest/` 패키지**(어댑터·싱크·CLI), 진입점은 루트 **`ingest.py`** 입니다.

- **RDB**: `t2s_tables`, `t2s_columns`, `t2s_fk_constraints` upsert
- **AGE** (기본): `ontology_graph`에 **Database** / **Table** / **Column** / **HAS_TABLE** / **HAS_COLUMN** / **FK_TO** (`_meta_ingest` 마커, 정점 매칭용 `_physical_vertex_id`)

## 운영 재현·식별자 (2.4 개념)

**“고정 환경 변수 블록 + 감사 로그”** 를 한곳에 모아 두자는 뜻이다. 같은 GraphDB에 재현 가능한 적재를 하려면 **원천·타깃·`META_DB_LABEL` 조합**이 명령마다 흔들리지 않아야 하므로, README에 **표준 PowerShell 예시**를 두고, 실행 시 stdout에 출력되는 **`ingest_audit:`** 줄과 보관한 `catalog.json`의 `meta_db_label` / `source_engine` / `source`(호스트·포트·dbname만)로 출처를 대조한다. (과거 초안에서 말한 “해당 문서”는 이 **재현·감사 절차를 README에 명시**한다는 의미.)

- **`META_DB_LABEL`**: 옵션 B — **짧은 논리 ID만** (`^[a-z0-9_]+$`, 엔진 코드·컨테이너명 **미포함**). 엔진은 **`SOURCE_ENGINE` / 카탈로그 `source_engine`**.
- **비밀 제외**: 카탈로그 `source` 및 로그에는 **비밀번호·계정명 등 미포함** (`catalog_validate`).

```powershell
cd services\meta_ingest_proto
pip install -r requirements.txt
$env:PYTHONPATH="C:\...\K_Water_v1\libs"
$env:META_DB_LABEL="kwater_rwis_prod"
$env:SOURCE_PG_HOST="127.0.0.1"
$env:SOURCE_PG_PORT="5432"
$env:SOURCE_PG_DB="rwis"
$env:SOURCE_PG_SCHEMA="RWIS"
$env:TARGET_PG_HOST="127.0.0.1"
$env:TARGET_PG_PORT="15434"
python ingest.py run
```

적재 후 AGE에서 `:Database` / `HAS_TABLE` 샘플: `scripts/verify_age_physical_database.sql`.

## 전제

- 대상 DB( GraphDB ): 로컬에서 `kair-graphdb-t2s` 이미지 컨테이너가 떠 있고, 호스트 포트 **15433** → 컨테이너 5432.
- 원천 DB: `robo-postgres` (`postgres:15-alpine`), 호스트 포트 **5432**. DB 이름 `rwis`, 스키마 이름 **`RWIS`** (대문자).

## 빌드

리포지토리 **루트**에서 빌드합니다 (`libs/age_graph_repository.physical_meta` 포함).

```powershell
cd C:\Users\LSW\Documents\GitHub\K_Water_v1
docker build -f services/meta_ingest_proto/Dockerfile -t meta-ingest-proto:0.1 .
```

로컬 실행 시에도 `ingest.py`가 `libs`를 `sys.path`에 넣으므로, 루트에서:

```powershell
cd services\meta_ingest_proto
pip install -r requirements.txt
python ingest.py extract -o .\rwis_catalog.json
```

## CLI (`ingest.py`)

| 명령 | 설명 |
|------|------|
| (인자 없음) / 동일하게 `run` | 원천에서 catalog 구성 후 `t2s_*` upsert + **AGE 물리 그래프** (기본) |
| `extract -o path.json` | 원천만 읽어 catalog JSON (테이블·컬럼·**FK 목록** 포함) |
| `load -i path.json` | catalog만으로 `t2s_*` + AGE 적재 (`META_INGEST_SKIP_AGE_PHYSICAL=1` 이면 RDB만) |

호스트에서 직접:

```powershell
cd services\meta_ingest_proto
pip install -r requirements.txt
$env:SOURCE_PG_HOST="127.0.0.1"
python ingest.py extract -o .\rwis_catalog.json
python ingest.py load -i .\rwis_catalog.json
```

## 실행 (호스트 포트 경유 — 가장 단순)

원천/대상 모두 Docker가 게이트한 TCP 포트로 접근:

```powershell
docker run --rm meta-ingest-proto:0.1
```

`ENTRYPOINT`가 `python /app/ingest.py`이므로 인자를 이어 붙일 수 있다. 예: catalog 추출 후 호스트에 두려면 볼륨 마운트:

```powershell
docker run --rm -v ${PWD}:/out -e SOURCE_PG_HOST=host.docker.internal meta-ingest-proto:0.1 extract -o /out/rwis_catalog.json
```

기본값이 `host.docker.internal` + 포트 5432/15433 을 가리킵니다.

## 실행 (Docker 네트워크 2개 부착)

컨테이너 이름으로 직접 붙을 때:

```powershell
docker create --name meta-ingest-run --network k-air-graphdb-t2s_default `
  -e SOURCE_PG_HOST=robo-postgres -e SOURCE_PG_PORT=5432 `
  -e TARGET_PG_HOST=kair-graphdb-t2s -e TARGET_PG_PORT=5432 `
  meta-ingest-proto:0.1
docker network connect robo-network meta-ingest-run
docker start -a meta-ingest-run
docker rm meta-ingest-run
```

## 환경 변수

| 변수 | 기본 | 설명 |
|------|------|------|
| `SOURCE_PG_HOST` | `host.docker.internal` | 원천 Postgres 호스트 |
| `SOURCE_PG_PORT` | `5432` | |
| `SOURCE_PG_USER` | `postgres` | |
| `SOURCE_PG_PASSWORD` | `postgres123` | |
| `SOURCE_PG_DB` | `rwis` | **데이터베이스 이름** |
| `SOURCE_PG_SCHEMA` | `RWIS` | 크롤할 **스키마** (Postgres 식별자 대소문자 유의) |
| `TARGET_PG_HOST` | `host.docker.internal` | GraphDB(Postgres) 호스트 |
| `TARGET_PG_PORT` | `15433` | 호스트 매핑 포트 |
| `TARGET_PG_USER` | `kair` | |
| `TARGET_PG_PASSWORD` | `kair_pass` | |
| `TARGET_PG_DB` | `kair_graphdb_t2s` | |
| `META_DB_LABEL` | `rwis_robo_postgres` | `t2s_tables.db` 논리 라벨 (`UNIQUE(db, schema_name, name)`) |
| `SOURCE_ENGINE` | `postgres` | 추출기: `postgres` \| `oracle` \| `mysql` \| `tibero` (후자 세 개는 골격·`NotImplementedError`) |
| `META_INGEST_SKIP_AGE_PHYSICAL` | (비움) | `1` / `true` 이면 AGE Table/Column 적재 생략, `t2s_*`만 |
| `META_AGE_GRAPH_NAME` | `ontology_graph` | AGE 그래프 이름 (`create_graph` 선행 필요) |

**운영 주의**: Neo4j→AGE `full` / `graph-only` 이관은 AGE에 Neo4j 출처 Table을 다시 깐다. **운영 DB catalog를 물리 정본으로 쓸 때**는 그 모드와 동시에 쓰지 말고, 온톨로지만 [`scripts/migrate_age/migrate_neo4j_to_age.py`](../../scripts/migrate_age/migrate_neo4j_to_age.py) `--mode ontology-only` 를 사용한다. 이 스크립트가 만든 Table/Column은 `_meta_ingest`로 삭제·재적재하며 Neo4j 이관 노드(마커 없음)와 구분된다.

## 검증 쿼리 (GraphDB 쪽)

```sql
SELECT COUNT(*) FROM t2s_tables WHERE db = 'rwis_robo_postgres' AND schema_name = 'RWIS';
SELECT COUNT(*) FROM t2s_columns c
  JOIN t2s_tables t ON t.id = c.table_id
  WHERE t.db = 'rwis_robo_postgres' AND t.schema_name = 'RWIS';
SELECT COUNT(*) FROM t2s_fk_constraints;
```

AGE (`psql`에서):

```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table) WHERE t._meta_ingest = true RETURN count(t)
$$) AS (c agtype);
SELECT * FROM cypher('ontology_graph', $$
  MATCH (t:Table)-[h:HAS_COLUMN]->(c:Column)
  WHERE t._meta_ingest = true AND c._meta_ingest = true
  RETURN count(h)
$$) AS (c agtype);
```

(FK_TO 관계에는 마커를 두지 않음; 샘플로 `MATCH (a)-[r:FK_TO]->(b) RETURN r LIMIT 5` 로 확인.)

로컬에서:

```powershell
docker exec -it kair-graphdb-t2s psql -U kair -d kair_graphdb_t2s -c "SELECT COUNT(*) FROM t2s_tables WHERE db = 'rwis_robo_postgres';"
```

## 스크립트 (`services/meta_ingest_proto/scripts/`)

| 파일 | 용도 |
|------|------|
| `verify_source_min_rwis.sql` | 최소 원천(테이블 2개) |
| `verify_source_5tables_rwis.sql` | 5테이블·FK 3건 원천 (`META_DB_LABEL=verify_5tables_rwis` 와 함께 사용) |
| `wipe_t2s_verify_5tables_rwis.sql` | 해당 라벨의 `t2s_tables` 행 삭제(재적재 전) |
| `verify_age_queries.sql` | AGE 샘플 매칭 |
| `verify_age_property_keys.sql` | `keys(t)`, 선택 테이블 `keys(c)` |
| `verify_age_physical_database.sql` | `:Database`·`HAS_TABLE` 건수 샘플 |

**Step 1 검증:** `scripts/` 디렉터리 SQL을 사용한다. 선택적 실행 요약 로그는 통합 작업 환경(예: K_Water_v1 `docs/step1_completion_bundle/VERIFICATION_LOG.md`)에 보관할 수 있다.
