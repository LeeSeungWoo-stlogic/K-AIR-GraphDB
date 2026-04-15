"""
PgBusinessCalendarService — business_calendar_service.py의 Neo4j 전환.

BusinessCalendar, NonBusinessDay, Holiday CRUD를 PostgreSQL로 전환.
"""

import logging
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class PgBusinessCalendarService:
    """PostgreSQL 기반 비즈니스 캘린더 서비스"""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def fetch_all_calendars(self) -> Dict[str, List]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.id, c.name, c.description, c.year, c.created_at, c.updated_at,
                          (SELECT count(*) FROM analyzer_non_business_days nbd WHERE nbd.calendar_id = c.id) AS nbd_count,
                          (SELECT count(*) FROM analyzer_holidays h WHERE h.calendar_id = c.id) AS holiday_count
                   FROM analyzer_business_calendars c ORDER BY c.name"""
            )
            return {"calendars": [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "description": r["description"] or "",
                    "year": r["year"],
                    "nonBusinessDayCount": r["nbd_count"],
                    "holidayCount": r["holiday_count"],
                }
                for r in rows
            ]}

    async def create_calendar(self, name: str, description: str = "", year: Optional[int] = None) -> Dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO analyzer_business_calendars (name, description, year)
                   VALUES ($1, $2, $3) RETURNING id, name""",
                name, description, year,
            )
            return {"id": str(row["id"]), "name": row["name"], "message": "캘린더가 생성되었습니다."}

    async def fetch_calendar_by_id(self, calendar_id: int) -> Optional[Dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description, year FROM analyzer_business_calendars WHERE id = $1",
                calendar_id,
            )
            if not row:
                return None

            nbds = await conn.fetch(
                "SELECT id, date, reason, day_type FROM analyzer_non_business_days WHERE calendar_id = $1 ORDER BY date",
                calendar_id,
            )
            holidays = await conn.fetch(
                "SELECT id, date, name, holiday_type FROM analyzer_holidays WHERE calendar_id = $1 ORDER BY date",
                calendar_id,
            )

            return {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "year": row["year"],
                "nonBusinessDays": [
                    {"id": str(n["id"]), "date": str(n["date"]), "reason": n["reason"], "dayType": n["day_type"]}
                    for n in nbds
                ],
                "holidays": [
                    {"id": str(h["id"]), "date": str(h["date"]), "name": h["name"], "holidayType": h["holiday_type"]}
                    for h in holidays
                ],
            }

    async def delete_calendar(self, calendar_id: int) -> Dict:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM analyzer_business_calendars WHERE id = $1", calendar_id)
            return {"message": "캘린더가 삭제되었습니다.", "deleted": True}

    async def add_non_business_day(self, calendar_id: int, date: str, reason: str = "", day_type: str = "non_business") -> Dict:
        import datetime as _dt
        date_obj = _dt.date.fromisoformat(date) if isinstance(date, str) else date
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO analyzer_non_business_days (calendar_id, date, reason, day_type)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (calendar_id, date) DO UPDATE SET reason = EXCLUDED.reason
                   RETURNING id""",
                calendar_id, date_obj, reason, day_type,
            )
            return {"id": str(row["id"]), "message": "비영업일이 추가되었습니다."}

    async def add_holiday(self, calendar_id: int, date: str, name: str, holiday_type: str = "public") -> Dict:
        import datetime as _dt
        date_obj = _dt.date.fromisoformat(date) if isinstance(date, str) else date
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO analyzer_holidays (calendar_id, date, name, holiday_type)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (calendar_id, date) DO UPDATE SET name = EXCLUDED.name
                   RETURNING id""",
                calendar_id, date_obj, name, holiday_type,
            )
            return {"id": str(row["id"]), "message": "공휴일이 추가되었습니다."}
