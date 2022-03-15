from http.client import HTTPException
from typing import Optional

from fastapi import Depends
from pydantic import ValidationError
from starlette.status import HTTP_403_FORBIDDEN

from server.models.auth import User

from .exceptions import AuthError, UserNotFound
from .sessions import UserSession, get_session_manager, session_cookie


def require_session_cookie(session_id: str = Depends(session_cookie)):
    if session_id is None:
        raise HTTPException(HTTP_403_FORBIDDEN, "missing session_cookie id")
    return session_id


async def get_session(
    session_id: str = Depends(session_cookie),
) -> Optional[UserSession]:
    return await get_session_manager().get(session_id, UserSession)


async def require_session(
    session_id: str = Depends(require_session_cookie),
):
    data = await get_session_manager().get(session_id)
    if data is None:
        raise HTTPException(401, "invalid or expired session_cookie")
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
