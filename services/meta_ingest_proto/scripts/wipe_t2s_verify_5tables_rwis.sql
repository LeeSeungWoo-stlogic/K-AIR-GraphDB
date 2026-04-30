-- GraphDB(t2s)에서 verify_5tables_rwis 라벨 메타만 제거 (자식 컬럼·FK는 CASCADE)
-- 사용 예:
--   docker exec -i kair-graphdb-t2s psql -U kair -d kair_graphdb_t2s -f - < wipe_t2s_verify_5tables_rwis.sql
-- 전용 E2E 인스턴스면: docker exec -i kair-graphdb-meta-e2e psql ...

DELETE FROM t2s_tables WHERE db = 'verify_5tables_rwis';
