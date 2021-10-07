from typing import Optional

import fastapi
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from starlette.responses import Response

from server.auth.models import User
from server.auth.utils import CurrentUser, find_user_by_credentials

router = fastapi.routing.APIRouter()


@router.get('/user', response_model=User)
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


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str]
    token_type: str = 'bearer'


@router.post('/token', response_model=LoginResponse)
async def login_user(credentials: OAuth2PasswordRequestForm = Depends()):
    user = await find_user_by_credentials(credentials.username, credentials.password)
    if user is not None:
        response = LoginResponse(
            access_token=user.create_token().encode(),
            refresh_token=user.create_token(token_type='refresh').encode(),
        )
        return Response(response.json())
    raise HTTPException(401, 'User with given credentials not found')
