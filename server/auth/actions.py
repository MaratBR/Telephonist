import secrets
from datetime import datetime, timedelta

from starlette.requests import Request
from starlette.responses import Response

from server.auth.models import UserSession

from .dependencies import session_cookie
from .models import User


async def _generate_session_id():
    session_id = secrets.token_urlsafe(20)
    while await UserSession.find({"_id": session_id}).exists():
        session_id = secrets.token_urlsafe(20)
    return session_id


async def create_user_session(request: Request, user: User, ttl: timedelta):
    session = UserSession(
        id=await _generate_session_id(),
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
        is_superuser=user.is_superuser,
        expires_at=datetime.utcnow() + ttl,
        renew_at=datetime.utcnow() + ttl - timedelta(days=2),
    )
    await session.save()
    return session


def set_session(
    response: Response,
    session: UserSession,
    ttl: timedelta,
    secure: bool,
    samesite: str,
):
    response.set_cookie(
        session_cookie.cookie,
        session.id,
        httponly=True,
        max_age=int(ttl.total_seconds()),
        secure=secure,
        samesite=samesite,
    )


async def renew_session(
    request: Request, old_session: UserSession, ttl: timedelta
):
    session = UserSession(
        id=await _generate_session_id(),
        user_id=old_session.user_id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
        is_superuser=old_session.is_superuser,
        expires_at=datetime.utcnow() + ttl,
        renew_at=datetime.utcnow() + ttl - timedelta(days=2),
    )
    await session.insert()
    return session
