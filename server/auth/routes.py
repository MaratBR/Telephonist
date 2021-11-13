from typing import Optional

import fastapi
from fastapi import HTTPException, Cookie, Body
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from starlette import status
from starlette.responses import Response

from server.auth.models import User, RefreshToken
from server.auth.utils import CurrentUser, find_user_by_credentials, HybridLoginData, TokenResponse, JWT_REFRESH_COOKIE
from server.settings import settings

router = fastapi.routing.APIRouter()


@router.get('/user', response_model=User.View)
async def get_user(user: User = CurrentUser(required=True)):
    user = User.View(**user.dict())
    return Response(user.json())


class NewUserInfo(BaseModel):
    username: str
    password: str


@router.post('/register')
async def register_new_user(info: NewUserInfo):
    try:
        await User.create_user(info.username, info.password)
    except DuplicateKeyError:
        raise HTTPException(409, 'User with given username already exists')
    return {
        'detail': "New user registered successfully"
    }


@router.post('/token')
async def login_user(credentials: HybridLoginData):
    user = await find_user_by_credentials(credentials.login, credentials.password)
    if user is not None:
        db_token, refresh_token = await RefreshToken.create_token(user, settings.refresh_token_lifetime)
        response = TokenResponse(
            user.create_token(scope=set(credentials.scope or set())),
            refresh_token,
            hybrid=credentials.hybrid,
            refresh_cookie_path=router.url_path_for('refresh')
        )
        return response
    raise HTTPException(401, 'User with given credentials not found')


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post('/refresh')
async def refresh(
        refresh_cookie: Optional[str] = Cookie(JWT_REFRESH_COOKIE),
        body: Optional[RefreshRequest] = Body(None),
):
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
        hybrid=refresh_cookie is not None,  # TODO проверить не лучше ли сделать более explicit это все
        refresh_cookie_path=router.url_path_for('refresh')
    )


