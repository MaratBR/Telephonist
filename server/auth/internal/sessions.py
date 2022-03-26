from datetime import datetime, timezone
from typing import Optional, TypeVar

from beanie import PydanticObjectId
from pydantic import Field

from server.common.models import AppBaseModel

TSessionData = TypeVar("TSessionData", bound=AppBaseModel)
TSessionID = TypeVar("TSessionID")


class InMemorySessionBackend(SessionsBackend):
    def __init__(self):
        self._store = {}

    async def set(self, session_id: str, data: str):
        self._store[session_id] = data

    async def delete(self, session_id: str):
        if session_id in self._store:
            del self._store[session_id]

    async def exists(self, session_id: str) -> bool:
        return session_id in self._store

    async def get(self, session_id: str) -> Optional[str]:
        return self._store.get(session_id)


class UserSession(AppBaseModel):
    user_id: PydanticObjectId
    csrf_token: str = Field(default_factory=generate_csrf_token)
    logged_in_at: datetime = Field(
        default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc)
    )
