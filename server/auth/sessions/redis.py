import math
from typing import Optional, Type

import orjson
from aioredis import Redis
from pydantic import ValidationError

from server.auth.sessions._backend import SessionsBackend, TSessionData


class RedisSessionBackend(SessionsBackend):
    async def set(
        self, session_id: str, data: TSessionData, ttl: Optional[float] = None
    ):
        await self._redis.set(
            self._prefix + type(data).__name__ + ":" + session_id,
            data.json(),
            ex=None if ttl is None else math.ceil(ttl),
        )

    async def delete(self, session_id: str, session_class: Type[TSessionData]):
        await self._redis.delete(self._prefix + session_class.__name__ + ":" + session_id)

    async def exists(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> bool:
        return await self._redis.exists(
            self._prefix + session_class.__name__ + ":" + session_id
        )

    async def get(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> Optional[str]:
        data = await self._redis.get(
            self._prefix + session_class.__name__ + ":" + session_id
        )
        try:
            return session_class(**orjson.loads(data))
        except (orjson.JSONDecodeError, ValidationError):
            return None

    def __init__(self, redis: Redis, prefix: Optional[str] = None):
        self._prefix = prefix or "SESSIONS:"
        self._redis = redis
