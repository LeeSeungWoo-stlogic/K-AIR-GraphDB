"""
pgvector 벡터 검색 Repository (P1-06).

text2sql, 온톨로지 노드 시맨틱 검색 등에 사용되는 벡터 검색 모듈.
HNSW 인덱스 기반 코사인 유사도 검색을 제공한다.

임베딩 생성은 외부(Argus RAG Server 또는 SentenceTransformer)에서 수행하고,
이 모듈은 저장/검색/삭제만 담당한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .connection import AgeConnection


class VectorRepository:
    """pgvector 기반 벡터 검색 저장소.

    사용법::

        repo = VectorRepository(conn)
        await repo.upsert_table_embedding("t1", "users", embedding=[0.1, ...])
        results = await repo.search_tables(query_embedding=[0.1, ...], top_k=5)
    """

    def __init__(self, conn: AgeConnection):
        self._conn = conn

    # ==================================================================
    # 테이블 임베딩
    # ==================================================================

    async def upsert_table_embedding(
        self,
        table_id: str,
        dataset_name: str,
        embedding: Sequence[float],
        *,
        schema_name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """테이블 임베딩 upsert."""
        import json
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        sql = """
        INSERT INTO embedding_tables (id, dataset_name, schema_name, description, embedding, metadata, updated_at)
        VALUES ($1, $2, $3, $4, $5::vector, $6::jsonb, now())
        ON CONFLICT (id) DO UPDATE SET
            dataset_name = EXCLUDED.dataset_name,
            schema_name  = EXCLUDED.schema_name,
            description  = EXCLUDED.description,
            embedding    = EXCLUDED.embedding,
            metadata     = EXCLUDED.metadata,
            updated_at   = now()
        """
        await self._conn.execute_sql_status(
            sql, table_id, dataset_name, schema_name, description,
            _vec_str(embedding), meta_json,
        )

    async def search_tables(
        self,
        query_embedding: Sequence[float],
        top_k: int = 5,
        *,
        schema_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """테이블 벡터 유사도 검색 (코사인).

        Returns:
            [{"id", "dataset_name", "description", "similarity"}, ...]
        """
        where = "WHERE schema_name = $3" if schema_filter else ""
        args: list = [_vec_str(query_embedding), top_k]
        if schema_filter:
            args.append(schema_filter)

        sql = f"""
        SELECT id, dataset_name, schema_name, description,
               1 - (embedding <=> $1::vector) AS similarity
        FROM embedding_tables
        {where}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """
        rows = await self._conn.execute_sql(sql, *args)
        return [dict(r) for r in rows]

    # ==================================================================
    # 컬럼 임베딩
    # ==================================================================

    async def upsert_column_embedding(
        self,
        column_id: str,
        table_id: str,
        column_name: str,
        embedding: Sequence[float],
        *,
        data_type: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """컬럼 임베딩 upsert."""
        import json
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        sql = """
        INSERT INTO embedding_columns
            (id, table_id, column_name, data_type, description, embedding, metadata, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb, now())
        ON CONFLICT (id) DO UPDATE SET
            column_name = EXCLUDED.column_name,
            data_type   = EXCLUDED.data_type,
            description = EXCLUDED.description,
            embedding   = EXCLUDED.embedding,
            metadata    = EXCLUDED.metadata,
            updated_at  = now()
        """
        await self._conn.execute_sql_status(
            sql, column_id, table_id, column_name, data_type,
            description, _vec_str(embedding), meta_json,
        )

    async def search_columns(
        self,
        query_embedding: Sequence[float],
        top_k: int = 10,
        *,
        table_id_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """컬럼 벡터 유사도 검색."""
        where = "WHERE table_id = $3" if table_id_filter else ""
        args: list = [_vec_str(query_embedding), top_k]
        if table_id_filter:
            args.append(table_id_filter)

        sql = f"""
        SELECT c.id, c.table_id, c.column_name, c.data_type, c.description,
               t.dataset_name,
               1 - (c.embedding <=> $1::vector) AS similarity
        FROM embedding_columns c
        LEFT JOIN embedding_tables t ON t.id = c.table_id
        {where}
        ORDER BY c.embedding <=> $1::vector
        LIMIT $2
        """
        rows = await self._conn.execute_sql(sql, *args)
        return [dict(r) for r in rows]

    # ==================================================================
    # 쿼리 임베딩 (T2S 쿼리 캐시)
    # ==================================================================

    async def upsert_query_embedding(
        self,
        query_id: str,
        natural_query: str,
        embedding: Sequence[float],
        *,
        sql_query: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """쿼리 임베딩 upsert (유사 쿼리 캐시)."""
        import json
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        sql = """
        INSERT INTO embedding_queries (id, natural_query, sql_query, embedding, metadata)
        VALUES ($1, $2, $3, $4::vector, $5::jsonb)
        ON CONFLICT (id) DO UPDATE SET
            natural_query   = EXCLUDED.natural_query,
            sql_query       = EXCLUDED.sql_query,
            embedding       = EXCLUDED.embedding,
            metadata        = EXCLUDED.metadata,
            execution_count = embedding_queries.execution_count + 1,
            last_used_at    = now()
        """
        await self._conn.execute_sql_status(
            sql, query_id, natural_query, sql_query,
            _vec_str(embedding), meta_json,
        )

    async def search_similar_queries(
        self,
        query_embedding: Sequence[float],
        top_k: int = 3,
        min_similarity: float = 0.85,
    ) -> List[Dict[str, Any]]:
        """유사 쿼리 검색 (캐시 히트).

        Returns:
            [{"natural_query", "sql_query", "similarity", "execution_count"}, ...]
        """
        sql = """
        SELECT id, natural_query, sql_query, execution_count,
               1 - (embedding <=> $1::vector) AS similarity
        FROM embedding_queries
        WHERE 1 - (embedding <=> $1::vector) >= $3
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """
        rows = await self._conn.execute_sql(
            sql, _vec_str(query_embedding), top_k, min_similarity,
        )
        return [dict(r) for r in rows]

    # ==================================================================
    # 온톨로지 노드 임베딩
    # ==================================================================

    async def upsert_ontology_node_embedding(
        self,
        embedding_id: str,
        node_id: str,
        embedding: Sequence[float],
        *,
        node_name: Optional[str] = None,
        node_label: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """온톨로지 노드 임베딩 upsert."""
        import json
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        sql = """
        INSERT INTO embedding_ontology_nodes
            (id, node_id, node_name, node_label, description, embedding, metadata, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb, now())
        ON CONFLICT (id) DO UPDATE SET
            node_name   = EXCLUDED.node_name,
            node_label  = EXCLUDED.node_label,
            description = EXCLUDED.description,
            embedding   = EXCLUDED.embedding,
            metadata    = EXCLUDED.metadata,
            updated_at  = now()
        """
        await self._conn.execute_sql_status(
            sql, embedding_id, node_id, node_name, node_label,
            description, _vec_str(embedding), meta_json,
        )

    async def search_ontology_nodes(
        self,
        query_embedding: Sequence[float],
        top_k: int = 10,
        *,
        label_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """온톨로지 노드 시맨틱 검색."""
        where = "WHERE node_label = $3" if label_filter else ""
        args: list = [_vec_str(query_embedding), top_k]
        if label_filter:
            args.append(label_filter)

        sql = f"""
        SELECT id, node_id, node_name, node_label, description,
               1 - (embedding <=> $1::vector) AS similarity
        FROM embedding_ontology_nodes
        {where}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """
        rows = await self._conn.execute_sql(sql, *args)
        return [dict(r) for r in rows]

    # ==================================================================
    # 유틸리티
    # ==================================================================

    async def delete_embedding(
        self,
        table_name: str,
        embedding_id: str,
    ) -> bool:
        """임베딩 레코드 삭제."""
        allowed = {
            "embedding_tables", "embedding_columns",
            "embedding_queries", "embedding_ontology_nodes",
        }
        if table_name not in allowed:
            raise ValueError(f"Invalid table: {table_name}")
        try:
            await self._conn.execute_sql_status(
                f"DELETE FROM {table_name} WHERE id = $1", embedding_id
            )
            return True
        except Exception:
            return False

    async def count_embeddings(self, table_name: str) -> int:
        """임베딩 테이블 레코드 수 카운트."""
        allowed = {
            "embedding_tables", "embedding_columns",
            "embedding_queries", "embedding_ontology_nodes",
        }
        if table_name not in allowed:
            raise ValueError(f"Invalid table: {table_name}")
        rows = await self._conn.execute_sql(
            f"SELECT count(*) AS cnt FROM {table_name}"
        )
        return rows[0]["cnt"] if rows else 0


def _vec_str(embedding: Sequence[float]) -> str:
    """Python float 리스트 → pgvector 문자열 '[0.1,0.2,...]'."""
    return "[" + ",".join(str(float(v)) for v in embedding) + "]"
