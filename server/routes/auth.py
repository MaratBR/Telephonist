import secrets
from datetime import timedelta
from typing import Optional

import fastapi
from fastapi import Body, Header, HTTPException
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from starlette import status
from starlette.requests import Request

from server.internal.auth.dependencies import CurrentUser, UserToken
from server.internal.auth.schema import (
    JWT_REFRESH_COOKIE,
    HybridLoginData,
    TokenResponse,
)
from server.models.auth import RefreshToken, TokenModel, User, UserView
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


@auth_router.post("/set-password")
async def set_password(
    body: NewPassword,
    token: TokenModel = UserToken(token_type="password-reset"),
):
    user = await User.get(token.sub)
    if user is None or (
        user.last_password_changed is not None and user.last_password_changed > token.issued_at
    ):
        raise HTTPException(401, "user not found or token is no longer valid for the user")

    if len(body.password) == 0:
        raise HTTPException(400, "password cannot be empty")
    user.set_password(body.password)
    await user.save_changes()
    return {"detail": "Password changed successfully"}


@auth_router.post("/token")
async def login_user(credentials: HybridLoginData, request: Request):
    user = await User.find_user_by_credentials(credentials.login, credentials.password)
    if user is not None:
        if user.password_reset_required:
            password_token = user.create_token(
                token_type="password-reset", lifetime=timedelta(minutes=15)
            )
            response = TokenResponse(None, None, password_reset_token=password_token)
        else:
            db_token, refresh_token = await RefreshToken.create_token(
                user, settings.refresh_token_lifetime
            )
            check_string = secrets.token_urlsafe(10) if credentials.hybrid else None
            response = TokenResponse(
                user.create_token(check_string=check_string),
                refresh_token,
                refresh_cookie_path=request.scope["router"].url_path_for("refresh"),
                refresh_as_cookie=credentials.hybrid,
                check_string=check_string,
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
        refresh_token = body.refresh_token
    elif refresh_cookie is not None:
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

    return TokenResponse(
        user.create_token(),
        refresh_token if settings.rotate_refresh_token else None,
        refresh_cookie_path=request.scope["router"].url_path_for("refresh"),
    )
