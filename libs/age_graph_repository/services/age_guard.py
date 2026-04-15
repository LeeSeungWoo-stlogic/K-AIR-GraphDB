"""
AGE 연결 필수 데코레이터 — neo4j_guard.py 대체.

Neo4jService 대신 AgeService/AgeConnection 존재를 확인한다.
"""

import asyncio
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def requires_age(default_return: Any = None):
    """AGE 연결 필수 데코레이터.

    스토어 메서드 실행 전에 AGE 연결이 활성인지 확인한다.
    미연결이면 기본값을 반환하고 경고 로그를 출력한다.

    Args:
        default_return: 미연결 시 반환할 기본값.
                        callable이면 호출하여 새 인스턴스 반환 (mutable default 방지).
    """
    def decorator(func: Callable) -> Callable:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(
                f"@requires_age는 async 메서드에만 적용 가능: {func.__name__}"
            )

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            conn = getattr(self, "_conn", None) or getattr(self, "_age", None)
            if conn is None:
                prov = getattr(self, "_age_provider", None)
                if callable(prov):
                    conn = prov()

            if conn is None:
                logger.warning("AGE 연결 없음 — %s 건너뜀", func.__name__)
                return default_return() if callable(default_return) else default_return
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator
