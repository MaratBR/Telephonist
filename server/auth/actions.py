import secrets
from datetime import datetime, timedelta
from typing import Union

from beanie import PydanticObjectId
from starlette.requests import Request
from starlette.responses import Response

from server.auth.models import UserSession
from server.settings import settings

from ..common.channels import get_channel_layer
from .dependencies import session_cookie
from .models import User


async def _generate_session_id():
    session_id = secrets.token_urlsafe(20)
    while await UserSession.find({"_id": session_id}).exists():
        session_id = secrets.token_urlsafe(20)
    return session_id


async def create_user_session(request: Request, user: User):
    session = UserSession(
        id=await _generate_session_id(),
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
        is_superuser=user.is_superuser,
        expires_at=datetime.utcnow() + settings.get().session_lifetime,
        renew_at=datetime.utcnow()
        + settings.get().session_lifetime
        - timedelta(days=2),
    )
    await session.save()
    return session


def get_sessions(user_id: PydanticObjectId):
    return UserSession.find(UserSession.user_id == user_id).to_list()


async def close_session(session: Union[UserSession, str]):
    if isinstance(session, str):
        session_id = session
        session = await UserSession.find_one({"_id": session})
    else:
        session_id = session.id
        session = session

    if session:
        await session.delete()
        await get_channel_layer().group_send(
            f"session/{session_id}",
            "force_refresh",
            {"reason": "session_closed"},
        )


async def close_all_sessions(user_id: PydanticObjectId):
    sessions = await get_sessions(user_id)
    for session in sessions:
        await close_session(session)


def set_session(response: Response, session: UserSession):
    response.set_cookie(
        session_cookie.cookie,
        session.id,
        httponly=True,
        max_age=int(settings.get().session_lifetime.total_seconds()),
        secure=settings.get().cookies_policy.lower() == "none"
        or not settings.get().use_non_secure_cookies,
        samesite=settings.get().cookies_policy,
    )


async def renew_session(request: Request, old_session: UserSession):
    session = UserSession(
        id=await _generate_session_id(),
        user_id=old_session.user_id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
        is_superuser=old_session.is_superuser,
        expires_at=datetime.utcnow() + settings.get().session_lifetime,
        renew_at=datetime.utcnow()
        + settings.get().session_lifetime
        - timedelta(days=2),
    )
    await session.insert()
    return session
