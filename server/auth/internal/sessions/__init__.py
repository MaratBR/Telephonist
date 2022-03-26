from datetime import datetime
from typing import Optional

from beanie import PydanticObjectId
from pydantic import Field

from server.common.models import AppBaseModel

from ._backend import SessionsBackend
from .dependencies import CSRFToken, SessionCookie
from .in_memory import InMemorySessionBackend
from .redis import RedisSessionBackend
from .utils import generate_csrf_token, mask_csrf_token, unmask_token

__all__ = (
    "get_session_backend",
    "csrf_token",
    "init_sessions_backend",
    "InMemorySessionBackend",
    "RedisSessionBackend",
    "mask_csrf_token",
    "unmask_token",
)

_session_backend: SessionsBackend = InMemorySessionBackend()


class UserSession(AppBaseModel):
    user_id: PydanticObjectId
    user_agent: Optional[str] = None
    logged_in_at: datetime = Field(default_factory=datetime.now)
    ip_address: str
    csrf_token: str = Field(default_factory=generate_csrf_token)


def get_session_backend() -> SessionsBackend:
    assert _session_backend, "sessions backend is not initilized!"
    return _session_backend


session_cookie = SessionCookie(cookie="APISID", auto_error=False)
csrf_token = CSRFToken(
    header_name="X-CSRF-Token",
    safe_methods=["GET", "OPTIONS", "HEAD"],
)


def init_sessions_backend(backend: SessionsBackend):
    global _session_backend
    _session_backend = backend
