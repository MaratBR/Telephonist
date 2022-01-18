import secrets
from datetime import datetime, timedelta
from typing import Optional

import fastapi
from fastapi import Body, Cookie, Header, HTTPException
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from starlette import status
from starlette.requests import Request
from starlette.responses import Response

from server.internal.auth.dependencies import AccessToken, CurrentUser
from server.internal.auth.schema import (
    JWT_REFRESH_COOKIE,
    HybridLoginData,
    TokenResponse,
)
from server.internal.auth.token import JWT, PasswordResetToken, UserTokenModel
from server.models.auth import AuthLog, RefreshToken, User, UserView
from server.settings import settings

auth_router = fastapi.routing.APIRouter(tags=["auth"], prefix="/auth")


@auth_router.get("/user", response_model=UserView)
async def get_user(user: User = CurrentUser(required=True)):
    return user


class NewUserInfo(BaseModel):
    username: str
    password: str


@auth_router.post("/register")
async def register_new_user(info: NewUserInfo, host: Optional[str] = Header(None)):
    if settings.user_registration_unix_socket_only and host != settings.unix_socket_name:
        raise HTTPException(403, "User registration is only allowed through unix socket")
    try:
        await User.create_user(info.username, info.password)
    except DuplicateKeyError:
        raise HTTPException(409, "User with given username already exists")
    return {"detail": "New user registered successfully"}


class NewPassword(BaseModel):
    password: str


@auth_router.post("/token")
async def login_user(credentials: HybridLoginData, request: Request):
    user = await User.find_user_by_credentials(credentials.login, credentials.password)
    if user is not None:
        if user.password_reset_required:
            password_token = PasswordResetToken(
                sub=user.id, exp=datetime.now() + timedelta(minutes=30)
            ).encode()
            response = TokenResponse(None, None, password_reset_token=password_token)
            await AuthLog.log(
                "password-reset-login",
                user.id,
                request.headers.get("user-agent"),
                request.client.host,
            )
        else:
            db_token, refresh_token = await RefreshToken.create_token(
                user, settings.refresh_token_lifetime
            )
            check_string = secrets.token_urlsafe(10) if credentials.hybrid else None
            ttl = timedelta(hours=12)
            response = TokenResponse(
                user.create_token(ttl, check_string=check_string).encode(),
                refresh_token,
                refresh_cookie_path=request.scope["router"].url_path_for("refresh"),
                refresh_as_cookie=credentials.hybrid,
                check_string=check_string,
                token_exp=datetime.now() + ttl,
            )
            await AuthLog.log(
                "hybrid-login", user.id, request.headers.get("user-agent"), request.client.host
            )
        return response
    raise HTTPException(401, "User with given credentials not found")


class RefreshRequest(BaseModel):
    refresh_token: str


@auth_router.post("/refresh")
async def refresh(
    request: Request,
    body: Optional[RefreshRequest] = Body(None),
):
    refresh_cookie = request.cookies.get(JWT_REFRESH_COOKIE)
    if body is not None:
        refresh_as_cookie = False
        refresh_token = body.refresh_token
    elif refresh_cookie is not None:
        refresh_as_cookie = True
        refresh_token = refresh_cookie
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST)

    token = await RefreshToken.find_valid(refresh_token)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    user = await User.get(token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    if settings.rotate_refresh_token:
        await token.delete()
        refresh_token = (await RefreshToken.create_token(user, settings.refresh_token_lifetime))[1]

    await AuthLog.log(
        "hybrid-refresh" if refresh_as_cookie else "refresh",
        user.id,
        request.headers.get("user-agent"),
        request,
    )
    ttl = timedelta(hours=12)
    return TokenResponse(
        user.create_token(ttl),
        refresh_token if settings.rotate_refresh_token else None,
        refresh_cookie_path=request.scope["router"].url_path_for("refresh"),
        refresh_as_cookie=refresh_as_cookie,
        token_exp=datetime.now() + ttl,
    )


@auth_router.post("/logout")
async def logout(request: Request, refresh_token: str = Cookie(..., alias=JWT_REFRESH_COOKIE)):
    if refresh_token:
        token = await RefreshToken.find_valid(refresh_token)
        await token.delete()
        await AuthLog.log(
            "explicit-logout", token.user_id, request.headers.get("user-agent"), request
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RevokeRefreshToken(BaseModel):
    token: str


@auth_router.post("/revoke-token")
async def revoke_refresh_token(
    request: Request,
    body: RevokeRefreshToken,
    user_token: UserTokenModel = AccessToken(),
):
    token = await RefreshToken.find_valid(body.token)
    if token:
        await token.delete()
        await AuthLog.log(
            "revoke-refresh-token", token.user_id, request.headers.get("user-agent"), request
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ResetPassword(BaseModel):
    password_reset_token: JWT[PasswordResetToken]
    new_password: str


@auth_router.post("/reset-password")
async def reset_password(body: ResetPassword, request: Request):
    user = await User.get(body.password_reset_token.model.sub)
    if not user.password_reset_required:
        raise HTTPException(status.HTTP_409_CONFLICT, "password already has been reset")
    user.set_password(body.new_password)
    await user.replace()
    await AuthLog.log("password-reset", user.id, request.headers.get("user-agent"), request)
    return {"detail": "Password reset"}
