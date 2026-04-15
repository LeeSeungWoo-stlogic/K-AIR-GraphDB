"""
PgGlossaryService — glossary_manage_service.py의 Neo4j 전환.

Glossary, Term, Domain, Owner, Tag CRUD를 PostgreSQL로 전환.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PgGlossaryService:
    """PostgreSQL 기반 용어집 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    # ── Glossary CRUD ──

    async def fetch_all_glossaries(self) -> Dict[str, List]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT g.id, g.name, g.description, g.type, g.created_at, g.updated_at,
                          (SELECT count(*) FROM analyzer_terms t WHERE t.glossary_id = g.id) AS term_count
                   FROM analyzer_glossaries g ORDER BY g.name"""
            )
            return {"glossaries": [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "description": r["description"] or "",
                    "type": r["type"] or "Business",
                    "termCount": r["term_count"],
                    "createdAt": str(r["created_at"]) if r["created_at"] else None,
                    "updatedAt": str(r["updated_at"]) if r["updated_at"] else None,
                }
                for r in rows
            ]}

    async def create_glossary(self, name: str, description: str, type_: str) -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO analyzer_glossaries (name, description, type)
                   VALUES ($1, $2, $3) RETURNING id, name""",
                name, description, type_,
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "용어집이 생성되었습니다."}

    async def fetch_glossary_by_id(self, glossary_id: int) -> Optional[Dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT g.id, g.name, g.description, g.type, g.created_at, g.updated_at,
                          (SELECT count(*) FROM analyzer_terms t WHERE t.glossary_id = g.id) AS term_count
                   FROM analyzer_glossaries g WHERE g.id = $1""",
                glossary_id,
            )
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "type": row["type"] or "Business",
                "termCount": row["term_count"],
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }

    async def update_glossary(self, glossary_id: int, **kwargs) -> Dict:
        sets, args, idx = [], [], 1
        for key in ("name", "description", "type"):
            val = kwargs.get(key)
            if val is not None:
                sets.append(f"{key} = ${idx}")
                args.append(val)
                idx += 1
        sets.append(f"updated_at = ${idx}")
        args.append(datetime.now(timezone.utc))
        idx += 1
        args.append(glossary_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE analyzer_glossaries SET {', '.join(sets)} WHERE id = ${idx}",
                *args,
            )
            return {"message": "용어집이 수정되었습니다.", "updated": "UPDATE 1" in result}

    async def delete_glossary(self, glossary_id: int) -> Dict:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM analyzer_glossaries WHERE id = $1", glossary_id)
            return {"message": "용어집이 삭제되었습니다.", "deleted": True}

    # ── Term CRUD ──

    async def fetch_terms(self, glossary_id: int, search: Optional[str] = None, limit: int = 100) -> Dict:
        async with self._pool.acquire() as conn:
            where = "t.glossary_id = $1"
            args: list = [glossary_id]
            if search:
                where += " AND lower(t.name) LIKE $2"
                args.append(f"%{search.lower()}%")

            rows = await conn.fetch(
                f"""SELECT t.id, t.name, t.description, t.status,
                           ARRAY(SELECT d.name FROM analyzer_term_domains td
                                 JOIN analyzer_domains d ON d.id = td.domain_id WHERE td.term_id = t.id) AS domains,
                           ARRAY(SELECT tg.name FROM analyzer_term_tags tt
                                 JOIN analyzer_tags tg ON tg.id = tt.tag_id WHERE tt.term_id = t.id) AS tags
                    FROM analyzer_terms t WHERE {where}
                    ORDER BY t.name LIMIT {limit}""",
                *args,
            )
            return {"terms": [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "description": r["description"] or "",
                    "status": r["status"] or "Draft",
                    "domains": list(r["domains"] or []),
                    "tags": list(r["tags"] or []),
                }
                for r in rows
            ]}

    async def create_term(self, glossary_id: int, term_data: Dict) -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO analyzer_terms (glossary_id, name, description, status)
                   VALUES ($1, $2, $3, $4) RETURNING id, name""",
                glossary_id,
                term_data.get("name", ""),
                term_data.get("description", ""),
                term_data.get("status", "Draft"),
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "용어가 생성되었습니다."}

    async def fetch_term_by_id(self, glossary_id: int, term_id: int) -> Optional[Dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT t.id, t.name, t.description, t.status, t.synonyms,
                          ARRAY(SELECT d.name FROM analyzer_term_domains td
                                JOIN analyzer_domains d ON d.id = td.domain_id WHERE td.term_id = t.id) AS domains,
                          ARRAY(SELECT tg.name FROM analyzer_term_tags tt
                                JOIN analyzer_tags tg ON tg.id = tt.tag_id WHERE tt.term_id = t.id) AS tags,
                          ARRAY(SELECT o.name FROM analyzer_term_owners tow
                                JOIN analyzer_owners o ON o.id = tow.owner_id WHERE tow.term_id = t.id) AS owners
                   FROM analyzer_terms t WHERE t.glossary_id = $1 AND t.id = $2""",
                glossary_id,
                term_id,
            )
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "status": row["status"] or "Draft",
                "synonyms": list(row["synonyms"] or []),
                "domains": list(row["domains"] or []),
                "tags": list(row["tags"] or []),
                "owners": list(row["owners"] or []),
            }

    async def update_term(self, glossary_id: int, term_id: int, term_data: Dict) -> Dict:
        sets, args, idx = [], [], 1
        for key in ("name", "description", "status"):
            val = term_data.get(key)
            if val is not None:
                sets.append(f"{key} = ${idx}")
                args.append(val)
                idx += 1
        if not sets:
            return {"message": "변경사항 없음", "updated": False}

        sets.append(f"updated_at = ${idx}")
        args.append(datetime.now(timezone.utc))
        idx += 1
        args.extend([glossary_id, term_id])

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE analyzer_terms SET {', '.join(sets)} WHERE glossary_id = ${idx} AND id = ${idx + 1}",
                *args,
            )
            return {"message": "용어가 수정되었습니다.", "updated": "UPDATE 1" in result}

    async def delete_term(self, glossary_id: int, term_id: int) -> Dict:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM analyzer_terms WHERE glossary_id = $1 AND id = $2",
                glossary_id, term_id,
            )
            return {"message": "용어가 삭제되었습니다.", "deleted": True}

    # ── Domain / Owner / Tag ──

    async def fetch_all_domains(self) -> Dict:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, description FROM analyzer_domains ORDER BY name")
            return {"domains": [{"id": str(r["id"]), "name": r["name"], "description": r["description"] or ""} for r in rows]}

    async def create_domain(self, name: str, description: str = "") -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO analyzer_domains (name, description) VALUES ($1, $2) RETURNING id, name",
                name, description,
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "도메인이 생성되었습니다."}

    async def fetch_all_owners(self) -> Dict:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, email, role FROM analyzer_owners ORDER BY name")
            return {"owners": [{"id": str(r["id"]), "name": r["name"], "email": r["email"] or "", "role": r["role"] or "Owner"} for r in rows]}

    async def create_owner(self, name: str, email: str, role: str) -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO analyzer_owners (name, email, role) VALUES ($1, $2, $3) RETURNING id, name",
                name, email, role,
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "소유자가 생성되었습니다."}

    async def fetch_all_tags(self) -> Dict:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, color FROM analyzer_tags ORDER BY name")
            return {"tags": [{"id": str(r["id"]), "name": r["name"], "color": r["color"] or "#3498db"} for r in rows]}

    async def create_tag(self, name: str, color: str) -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO analyzer_tags (name, color) VALUES ($1, $2) RETURNING id, name",
                name, color,
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "태그가 생성되었습니다."}
