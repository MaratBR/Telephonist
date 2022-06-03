from typing import Optional, Union
from uuid import UUID

import httpagentparser
from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import SecretStr
from starlette import status
from starlette.requests import Request
from starlette.responses import Response

from server.auth.dependencies import get_session, superuser
from server.auth.models import AuthLog, User, UserSession, UserView
from server.auth.services import SessionsService, UserService
from server.common.channels import get_channel_layer
from server.common.channels.layer import ChannelLayer
from server.common.models import AppBaseModel, Pagination
from server.l10n import gettext as _

users_router = APIRouter(prefix="/users")


class UsersPagination(Pagination):
    descending_by_default = True
    default_order_by = "username"
    ordered_by_options = {"_id", "username"}
    fields_mapping = {"username": "normalized_username"}


@users_router.get("")
async def get_users(
    pagination: UsersPagination = Depends(),
):
    return await pagination.paginate(User, UserView)


class CreateUser(AppBaseModel):
    username: str
    is_superuser: bool = False
    password: SecretStr


@users_router.post("", status_code=201, dependencies=[Depends(superuser)])
async def create_user(
    data: CreateUser = Body(...), users_service: UserService = Depends()
):
    user = await users_service.create_user(
        data.username,
        data.password.get_secret_value(),
        True,
        data.is_superuser,
    )
    return UserView(**user.dict(by_alias=True))


async def get_user(user_id: Union[PydanticObjectId, str]):
    if isinstance(user_id, str):
        try:
            q = User.find_one({"_id": PydanticObjectId(user_id)})
        except InvalidId:
            q = User.find_one({"normalized_username": user_id.upper()})
    else:
        q = User.find_one({"_id": user_id})
    user = await q
    if user is None:
        raise HTTPException(404, f"user with id {user_id} not found")
    return user


@users_router.get("/{user_id}")
async def get_user_detailed(
    user_id: str,
):
    user = await get_user(user_id)
    return {
        "user": UserView(**user.dict(by_alias=True)),
        "sessions": [
            {
                "id": s.ref_id,
                "user_agent": {
                    "raw": s.user_agent,
                    "detected": httpagentparser.detect(s.user_agent),
                },
                "ip": s.ip_address,
                "created_at": s.logged_in_at,
            }
            for s in await UserSession.find(
                UserSession.user_id == user.id
            ).to_list()
        ],
        "last_events": await AuthLog.find(AuthLog.user_id == user.id)
        .sort(("_id", SortDirection.DESCENDING))
        .limit(20)
        .to_list(),
    }


class BlockRequest(AppBaseModel):
    reason: Optional[str] = None


@users_router.post("/{user_id}/block")
async def block_user(
    request: Request,
    user_id: PydanticObjectId,
    data: BlockRequest = Body(BlockRequest()),
    session: UserSession = Depends(superuser),
    channel_layer: ChannelLayer = Depends(get_channel_layer),
    session_service: SessionsService = Depends(),
):
    user = await get_user(user_id)
    if not user.is_blocked:
        await user.block()
        await session_service.close_all_sessions(user.id)
        await AuthLog.log(
            "blocked",
            user.id,
            request.headers.get("user-agent"),
            request.client.host,
            {"blocked_by": session.user_id},
        )
        await channel_layer.group_send(
            f"u/{user_id}", "banned", {"reason": data.reason}
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.delete("/{user_id}/sessions/{session_ref_id}")
async def close_user_session(
    user_id: str,
    session_ref_id: UUID,
    session_service: SessionsService = Depends(),
):
    await get_user(user_id)
    session = await UserSession.find_one({"ref_id": session_ref_id})
    if session:
        await session_service.close(session)
        return {"detail": "Session closed"}


@users_router.delete("/{user_id}")
async def delete_user(
    user_id: PydanticObjectId,
    session: UserSession = Depends(get_session),
    user_service: UserService = Depends(),
):
    if user_id == session.user_id:
        raise HTTPException(403, _("You cannot deactivate your own account"))
    user = await User.get(user_id)
    if user is None or user.will_be_deleted_at:
        raise HTTPException(
            404, _("User not found or already scheduled for deletion")
        )
    _user, timeout = await user_service.deactivate_user(user)
    return {
        "detail": _("User will deactivated in about {0} days").format(
            timeout.days
        )
    }
