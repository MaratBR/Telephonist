from typing import Optional

from fastapi import Depends, HTTPException
from starlette.requests import Request
from starlette.status import HTTP_403_FORBIDDEN

from server.auth.models.auth import User

from .exceptions import AuthError, UserNotFound
from .sessions import (
    UserSession,
    csrf_token,
    get_session_backend,
    session_cookie,
)


def require_session_cookie(session_id: str = Depends(session_cookie)):
    if session_id is None:
        raise HTTPException(HTTP_403_FORBIDDEN, "missing session cookie")
    return session_id


async def get_session(
    session_id: str = Depends(session_cookie),
) -> Optional[UserSession]:
    if session_id is None:
        return None
    return await get_session_backend().get(session_id, UserSession)


async def require_session(
    session_id: str = Depends(require_session_cookie),
):
    data = await get_session_backend().get(session_id, UserSession)
    if data is None:
        raise HTTPException(401, "invalid or expired session cookie")
    return data


async def _require_current_user(
    session: UserSession = Depends(require_session),
) -> User:
    user = await User.get(session.user_id)
    if user is None:
        raise UserNotFound()
    return user


async def _current_user(
    session: UserSession = Depends(get_session),
) -> Optional[User]:
    if session:
        try:
            return await _require_current_user(session)
        except AuthError:
            return None
    return None


def CurrentUser(required: bool = True) -> User:  # noqa
    get = _require_current_user
    if not required:
        get = _current_user

    return Depends(get)


def validate_csrf_token(
    request: Request,
    token: str = Depends(csrf_token),
    session: UserSession = Depends(require_session),
):
    if request.method in ("GET", "OPTIONS", "HEAD"):
        return
    if token is None:
        raise HTTPException(
            HTTP_403_FORBIDDEN, "CSRF token is missing", headers={}
        )
    if token != session.csrf_token:
        raise HTTPException(HTTP_403_FORBIDDEN, "CSRF token mismatch")
