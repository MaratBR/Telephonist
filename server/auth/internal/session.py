import secrets
from typing import Union

from beanie import PydanticObjectId
from starlette.requests import Request

from server.auth.models.auth import PersistentUserSession, User
from server.auth.sessions import UserSession, get_session_backend
from server.common.channels import get_channel_layer
from server.settings import get_settings


async def _generate_session_id():
    session_id = secrets.token_urlsafe(20)
    while await get_session_backend().exists(session_id, UserSession):
        session_id = secrets.token_urlsafe(20)
    return session_id


async def create_user_session(request: Request, user: User):
    session = UserSession(
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host,
        is_superuser=user.is_superuser,
    )
    session_id = await _generate_session_id()
    await get_session_backend().set(
        session_id,
        session,
        ttl=get_settings().session_lifetime.total_seconds(),
    )
    session_obj = PersistentUserSession(_id=session_id, data=session)
    await session_obj.insert()
    return session_obj


def get_sessions(user_id: PydanticObjectId):
    return PersistentUserSession.find(
        PersistentUserSession.data.user_id == user_id
    ).to_list()


async def close_session(session: Union[PersistentUserSession, str]):
    if isinstance(session, str):
        session_id = session
        session_obj = await PersistentUserSession.find_one({"_id": session})
    else:
        session_id = session.id
        session_obj = session

    if await get_session_backend().exists(session_id, UserSession):
        await get_session_backend().delete(session_id, UserSession)
        await get_channel_layer().group_send(
            f"session/{session_id}",
            "force_refresh",
            {"reason": "session_closed"},
        )

    if session_obj:
        await session_obj.delete()


async def close_all_sessions(user_id: PydanticObjectId):
    sessions = await get_sessions(user_id)
    for session in sessions:
        await close_session(session)
