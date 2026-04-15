FROM postgres:16

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libreadline-dev \
        zlib1g-dev \
        flex \
        bison \
        git \
        postgresql-server-dev-16 \
        ca-certificates \
    && git clone --branch release/PG16/1.5.0 --depth 1 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make install \
    && git clone --branch v0.7.4 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector && make install \
    && apt-get purge -y build-essential git flex bison postgresql-server-dev-16 \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /tmp/age /tmp/pgvector
