import secrets
from datetime import datetime, timedelta
from typing import Optional

import fastapi
from fastapi import Body, Depends, Header, HTTPException
from pymongo.errors import DuplicateKeyError
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from server.auth.internal.dependencies import get_session, require_session
from server.auth.internal.sessions import (
    UserSession,
    get_session_backend,
    mask_csrf_token,
    session_cookie,
)
from server.auth.internal.token import JWT, PasswordResetToken
from server.auth.models.auth import AuthLog, User, UserView
from server.common.models import AppBaseModel
from server.settings import settings

auth_router = fastapi.routing.APIRouter(tags=["auth"], prefix="/auth")


class NewUserInfo(AppBaseModel):
    username: str
    password: str


@auth_router.post("/register")
async def register_new_user(
    info: NewUserInfo, host: Optional[str] = Header(None)
):
    if (
        settings.user_registration_unix_socket_only
        and host != settings.unix_socket_name
    ):
        raise HTTPException(
            403, "User registration is only allowed through unix socket"
        )
    try:
        await User.create_user(info.username, info.password)
    except DuplicateKeyError:
        raise HTTPException(409, "User with given username already exists")
    return {"detail": "New user registered successfully"}


class LoginResponse(JSONResponse):
    def __init__(self, cookie_name: str, session_id: str):
        super(LoginResponse, self).__init__({"detail": "Logged in"})
        self.session_id = session_id
        self.set_cookie(
            cookie_name,
            session_id,
            httponly=True,
            max_age=settings.session_lifetime.total_seconds(),
            secure=not settings.use_non_secure_cookies,
            samesite=settings.cookies_policy,
        )


class PasswordResetRequiredResponse(JSONResponse):
    def __init__(self, reset_token: str, expiration: datetime):
        super(PasswordResetRequiredResponse, self).__init__(
            {
                "detail": "Password reset required",
                "password_reset": {"token": reset_token, "exp": expiration},
            }
        )


class LoginRequest(AppBaseModel):
    username: str
    password: str


@auth_router.post("/login")
async def login_user(
    request: Request,
    credentials: LoginRequest = Body(...),
    session: UserSession = Depends(get_session),
    session_id: str = Depends(session_cookie),
):
    user = await User.find_user_by_credentials(
        credentials.username, credentials.password
    )
    if session and session.user_id == user.id:
        return LoginResponse(session_cookie.cookie, session_id)
    if user is not None:
        if user.password_reset_required:
            exp = datetime.now() + timedelta(minutes=10)
            password_token = PasswordResetToken(sub=user.id, exp=exp).encode()
            return PasswordResetRequiredResponse(password_token, exp)
        session_id = secrets.token_urlsafe(20)
        await get_session_backend().set(
            session_id,
            UserSession(
                user_id=user.id,
                user_agent=request.headers.get("user-agent"),
                ip_address=request.client.host,
            ),
        )
        return LoginResponse(session_cookie.cookie, session_id)
    raise HTTPException(401, "User with given credentials not found")


@auth_router.get("/whoami")
async def whoami(session_data: UserSession = Depends(get_session)):
    if session_data is None:
        return {
            "user": None,
            "session": None,
            "detail": "Who the heck are you?",
        }
    user = await User.get(session_data.user_id)
    return {
        "user": UserView(**user.dict(by_alias=True)),
        "session": session_data,
        "detail": "Here's who you are!",
    }


@auth_router.get("/csrf")
async def get_csrf_token(
    session_data: UserSession = Depends(require_session),
):
    masked = mask_csrf_token(session_data.csrf_token)
    return Response(masked, headers={"X-CSRF-Token": masked})


@auth_router.post("/logout")
async def logout(
    request: Request,
    session_id: str = Depends(session_cookie),
    session: UserSession = Depends(get_session),
):
    if session_id:
        if await get_session_backend().exists(session_id, UserSession):
            await get_session_backend().delete(session_id, UserSession)
            if session:
                await AuthLog.log(
                    "sessionLogout",
                    session.user_id,
                    ip_address_or_request=request.client.host,
                    user_agent=request.headers.get("user-agent"),
                )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RevokeRefreshToken(AppBaseModel):
    token: str


class ResetPassword(AppBaseModel):
    password_reset_token: JWT[PasswordResetToken]
    new_password: str


@auth_router.post("/reset-password")
async def reset_password(body: ResetPassword, request: Request):
    user = await User.get(body.password_reset_token.model.sub)
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
