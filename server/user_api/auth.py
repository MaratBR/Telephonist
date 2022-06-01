from datetime import datetime, timedelta, timezone
from typing import Optional

import fastapi
from beanie import PydanticObjectId
from fastapi import Body, Depends, HTTPException
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from server.auth.dependencies import (
    CurrentUser,
    get_session,
    require_session,
    session_cookie,
)
from server.auth.models import AuthLog, User, UserSession, UserView
from server.auth.services import (
    PasswordHashingService,
    SessionsService,
    TokenService,
    UserService,
)
from server.auth.token import PasswordResetToken
from server.auth.utils import mask_hex_token
from server.common.models import AppBaseModel
from server.exceptions import ApiException
from server.l10n import gettext as _
from server.settings import Settings, get_settings

auth_router = fastapi.routing.APIRouter(tags=["auth"], prefix="/auth")


class NewUserInfo(AppBaseModel):
    username: str
    password: str


class PasswordResetRequiredResponse(JSONResponse):
    def __init__(self, reset_token: str, expiration: datetime):
        super(PasswordResetRequiredResponse, self).__init__(
            {
                "detail": "Password reset required",
                "password_reset": {
                    "token": reset_token,
                    "exp": expiration.isoformat(),
                },
            }
        )


class LoginRequest(AppBaseModel):
    username: str
    password: str


@auth_router.post("/logout")
async def logout(
    response: Response,
    session: Optional[UserSession] = Depends(get_session),
    session_id: Optional[str] = Depends(session_cookie),
    sessions_service: SessionsService = Depends(),
):
    if session and session_id:
        await sessions_service.close(session_id)
        response.delete_cookie(session_cookie.cookie)
    return {"detail": "Bye, bye!"}


@auth_router.post("/login")
async def login_user(
    response: Response,
    credentials: LoginRequest = Body(...),
    session: Optional[UserSession] = Depends(get_session),
    session_id: Optional[str] = Depends(session_cookie),
    settings: Settings = Depends(get_settings),
    sessions_service: SessionsService = Depends(),
    token_service: TokenService = Depends(),
    user_service: UserService = Depends(),
):
    if await User.count() == 0:
        await user_service.create_default_user()

    user = await user_service.find_user_by_credentials(
        credentials.username, credentials.password
    )
    if user is None:
        raise HTTPException(401, _("User with given credentials not found"))
    if user.is_blocked:
        raise HTTPException(401, "User is blocked")

    if session and session_id:
        await sessions_service.close(session_id)

    if user.password_reset_required:
        exp = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(
            minutes=10
        )
        password_token = token_service.encode(
            PasswordResetToken(sub=user.id, exp=exp)
        )
        return PasswordResetRequiredResponse(password_token, exp)

    session_obj = await sessions_service.create(user)
    session_id = session_obj.id
    response.set_cookie(
        session_cookie.cookie,
        session_id,
        httponly=True,
        max_age=int(settings.session_lifetime.total_seconds()),
        secure=settings.use_https,
        samesite=settings.cookies_policy,
    )

    return {
        "user": UserView(**user.dict(by_alias=True)),
        "csrf": mask_hex_token(session_obj.csrf_token),
        "detail": "Logged in successfully",
        "session_ref_id": session_obj.ref_id,
    }


@auth_router.get("/whoami")
async def whoami(
    request: Request,
    session_data: UserSession = Depends(get_session),
    session_id: str = Depends(session_cookie),
):
    if session_data is None:
        return {
            "user": None,
            "session_ref_id": None,
            "detail": "Who the heck are you?",
            "ip": [request.client.host, request.client.port],
        }
    user = await User.get(session_data.user_id)
    session_obj = await UserSession.find_one({"_id": session_id})
    return {
        "user": UserView(**user.dict(by_alias=True)),
        "session_ref_id": None if session_obj is None else session_obj.ref_id,
        "detail": "Here's who you are!",
        "ip": [request.client.host, request.client.port],
    }


@auth_router.get("/csrf")
async def get_csrf_token(
    response: Response,
    session_data: UserSession = Depends(require_session),
):
    masked = mask_hex_token(session_data.csrf_token)
    response.headers["X-CSRF-Token"] = masked
    response.media_type = "text/plain"
    return masked


@auth_router.post("/logout")
async def logout(
    request: Request,
    session_id: str = Depends(session_cookie),
    session: UserSession = Depends(get_session),
):
    if session_id:
        session = await UserSession.find_one({"_id": session_id})
        if session:
            await session.delete()
            if session:
                await AuthLog.log(
                    "sessionLogout",
                    session.user_id,
                    ip_address_or_request=request.client.host,
                    user_agent=request.headers.get("user-agent"),
                )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ResetPassword(AppBaseModel):
    password_reset_token: str
    new_password: str


@auth_router.post("/reset-password")
async def reset_password(
    body: ResetPassword,
    request: Request,
    token_service: TokenService = Depends(),
):
    token = token_service.decode(PasswordResetToken, body.password_reset_token)
    user = await User.get(token.sub)
    if not user.password_reset_required:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "password already has been reset"
        )
    user.set_password(body.new_password)
    await user.replace()
    await AuthLog.log(
        "password-reset", user.id, request.headers.get("user-agent"), request
    )
    return {"detail": "Password reset"}


class ResetPasswordCurrentUser(AppBaseModel):
    new_password: str
    password: Optional[str]


@auth_router.post("/reset-password-current")
async def reset_password_for_current_user(
    body: ResetPasswordCurrentUser = Body(...),
    user: User = CurrentUser(),
    session_id: str = Depends(session_cookie),
    hashing_service: PasswordHashingService = Depends(),
    session_service: SessionsService = Depends(),
):
    if not hashing_service.verify_password(body.password, user.password_hash):
        raise ApiException(
            401, "password_reset.password_invalid", "Password is invalid!"
        )
    user.password_hash = hashing_service.hash_password(body.new_password)
    await user.save()
    sessions = await UserSession.find(UserSession.user_id == user.id).to_list()
    for session in sessions:
        if session.id == session_id:
            continue
        await session_service.close(session)
    return {"details": "Password changed successfully"}


@auth_router.delete("/delete-user/{user_id}")
async def delete_user(
    user_id: PydanticObjectId, user_service: UserService = Depends()
):
    user = await User.get(user_id)
    if user is None or user.will_be_deleted_at:
        raise HTTPException(
            404, "User not found or already scheduled for deletion"
        )
    await user_service.deactivate_user(user)
    return {"detail": "User has been deactivated"}
