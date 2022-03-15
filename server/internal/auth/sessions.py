import secrets
from abc import abstractmethod
from datetime import datetime, timezone
from http.client import HTTPException
from typing import Any, Generic, Literal, Optional, TypeVar, Type

import orjson
from aioredis import Redis
from beanie import PydanticObjectId
from fastapi.openapi.models import SecurityBase as SecurityBaseModel
from fastapi.security.base import SecurityBase
from pydantic import Field, ValidationError
from starlette.requests import Request

from server.models.common import AppBaseModel

TSessionData = TypeVar("TSessionData", bound=AppBaseModel)
TSessionID = TypeVar("TSessionID")


class SessionsBackend:
    @abstractmethod
    async def set(self, session_id: str, data: str):
        ...

    @abstractmethod
    async def delete(self, session_id: str):
        ...

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        ...

    @abstractmethod
    async def get(self, session_id: str) -> Optional[str]:
        ...


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


class RedisSessionBackend(SessionsBackend):
    async def set(self, session_id: str, data: str):
        await self._redis.set(self._prefix + session_id, data)

    async def delete(self, session_id: str):
        await self._redis.delete(self._prefix + session_id)

    async def exists(self, session_id: str) -> bool:
        return await self._redis.exists(self._prefix + session_id)

    async def get(self, session_id: str) -> Optional[str]:
        data = await self._redis.get(self._prefix + session_id)
        try:
            return data
        except orjson.JSONDecodeError:
            return None

    def __init__(self, redis: Redis, prefix: Optional[str] = None):
        self._prefix = prefix or "SESSIONS:"
        self._redis = redis


class SessionCookieModel(SecurityBaseModel):
    type_: Literal["apiKey"] = Field(alias="type", default="apiKey")
    in_: Literal["cookie"] = Field(alias="in", default="cookie")
    name: str


class SessionCookie(SecurityBase, Generic[TSessionID]):
    model: SessionCookieModel

    def __init__(
        self,
        cookie: str,
        *,
        schema_name: str = "SessionCookie",
        description: Optional[str] = None,
        auto_error: bool = True
    ):
        self.scheme_name = schema_name
        self.description = description
        self.auto_error = auto_error
        self.cookie = cookie
        self.model = SessionCookieModel(name=schema_name)

    def __call__(self, request: Request) -> Optional[str]:
        return request.cookies.get(self.cookie)


def generate_csrf_token():
    return secrets.token_urlsafe(20)


class UserSession(AppBaseModel):
    user_id: PydanticObjectId
    csrf_token: str = Field(default_factory=generate_csrf_token)
    logged_in_at: datetime = Field(
        default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc)
    )


class CSRFToken:
    def __init__(
        self, *, safe_methods: list[str], header_name: str, cookie_name: str
    ):
        self.header = header_name
        self.cookie = cookie_name
        self.safe_methods = safe_methods

    def __call__(self, request: Request):
        if request.method in self.safe_methods:
            return None
        token = request.headers.get(self.header)
        cookie_token = request.cookies.get(self.cookie)
        if token != cookie_token:
            raise HTTPException(401, "CSRF token mismatch")
        return token


class SessionManager:
    def __init__(self, backend: SessionsBackend):
        self.backend = backend

    async def get(self, session_id: str, session_class: Type[TSessionData]) -> Optional[TSessionData]:
        data = await self.backend.get(f'{session_class.__name__}:{session_id}')
        try:
            return session_class(**orjson.loads(data))
        except (ValidationError, orjson.JSONDecodeError):
            return None

    async def delete(self, session_id: str, session_class: Type[TSessionData]):
        await self.backend.delete(f'{session_class.__name__}:{session_id}')

    async def set(self, session_id: str, session_data: TSessionData):
        await self.backend.set(f'{type(session_data).__name__}:{session_id}', session_data.json())

    async def exists(self, session_id: str, session_class: Type[TSessionData]) -> bool:
        return await self.backend.exists(f'{session_class.__name__}:{session_id}')


_session_manager: Optional[SessionManager] = None
_session_backend: SessionsBackend = InMemorySessionBackend()


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(_session_backend)
    return _session_manager


session_cookie = SessionCookie(cookie="APISID", auto_error=False)
validate_csrf_token = CSRFToken(
    header_name="X-CSRF-Token",
    cookie_name="_xsrf",
    safe_methods=["GET", "OPTIONS"],
)


def init_redis_sessions(redis: Redis):
    global _session_backend, _session_manager
    _session_backend = RedisSessionBackend(redis)
    _session_manager = SessionManager(_session_backend)
