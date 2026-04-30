# Prototype worker — connects to source PostgreSQL + target K-AIR GraphDB (PG+AGE).
# Build from **repository root** (K_Water_v1):
#   docker build -f services/meta_ingest_proto/Dockerfile -t meta-ingest-proto:0.1 .
FROM python:3.12-slim

WORKDIR /app
COPY services/meta_ingest_proto/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# age_graph_repository.physical_meta 등
COPY libs/age_graph_repository /app/libs/age_graph_repository

COPY services/meta_ingest_proto/meta_ingest /app/meta_ingest
COPY services/meta_ingest_proto/ingest.py /app/ingest.py

ENV PYTHONPATH=/app/libs:/app \
    SOURCE_PG_HOST=host.docker.internal \
    SOURCE_PG_PORT=5432 \
    SOURCE_PG_USER=postgres \
    SOURCE_PG_PASSWORD=postgres123 \
    SOURCE_PG_DB=rwis \
    SOURCE_PG_SCHEMA=RWIS \
    TARGET_PG_HOST=host.docker.internal \
    TARGET_PG_PORT=15433 \
    TARGET_PG_USER=kair \
    TARGET_PG_PASSWORD=kair_pass \
    TARGET_PG_DB=kair_graphdb_t2s \
    META_DB_LABEL=rwis_robo_postgres

ENTRYPOINT ["python", "/app/ingest.py"]
