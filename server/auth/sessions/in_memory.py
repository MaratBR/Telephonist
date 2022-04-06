import time
from typing import Optional, Type

from server.auth.sessions._backend import SessionsBackend, TSessionData


class InMemorySessionBackend(SessionsBackend):
    def __init__(self):
        self._store = {}

    async def set(
        self, session_id: str, data: TSessionData, ttl: Optional[float] = None
    ):
        self._store[session_id] = [
            None if ttl is None else time.time() + ttl,
            data,
        ]

    async def delete(self, session_id: str, session_class: Type[TSessionData]):
        if session_id in self._store:
            del self._store[session_id]

    async def exists(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> bool:
        return session_id in self._store and (
            self._store[session_id][0] is None or self._store[session_id][0]
        )

    async def get(
        self, session_id: str, session_class: Type[TSessionData]
    ) -> Optional[TSessionData]:
        pair = self._store.get(session_id)
        if pair:
            exp, value = pair
            if exp is None:
                return value
            if exp < time.time():
                return value
            else:
                del self._store[session_id]
        return None
