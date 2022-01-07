import hashlib
from functools import partial, wraps
from typing import *

from fastapi import Cookie, Depends, params
from jose import JWTError
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from server.internal.auth.exceptions import AuthError, InvalidToken, UserNotFound
from server.internal.auth.schema import JWT_CHECK_HASH_COOKIE, bearer
from server.internal.auth.token import UserTokenModel
from server.internal.auth.utils import parse_resource_key
from server.models.auth import BlockedAccessToken, User
from server.settings import settings


def require_bearer(token: Optional[str] = Depends(bearer)):
    if token is None:
        raise InvalidToken("token is missing")
    return token


def _require_user_token(
    check_string: Optional[str] = Cookie(None, alias=JWT_CHECK_HASH_COOKIE),
    jwt: str = Depends(require_bearer),
):
    token = UserTokenModel.decode(jwt)
    if token.check_string:
        if (
            check_string is None
            or token.check_string != hashlib.sha256(check_string.encode()).hexdigest()
        ):
            raise InvalidToken(
                "jwt token check string is invalid or check string cookie"
                f' ("{JWT_CHECK_HASH_COOKIE}) is missing'
            )
    return token


def _get_user_token(
    check_string: Optional[str] = Cookie(None, alias=JWT_CHECK_HASH_COOKIE),
    jwt: str = Depends(bearer),
):
    if jwt is None:
        return None
    try:
        return _require_user_token(check_string, jwt)
    except InvalidToken:
        return None


def AccessToken(  # noqa N802
    required: bool = True,
):
    return Depends(_require_user_token if required else _get_user_token)


async def _require_current_user(token: UserTokenModel = AccessToken()) -> User:
    if await BlockedAccessToken.is_blocked(token.jti):
        raise AuthError("This token has been revoked")
    user = await User.get(token.sub)
    if user is None:
        raise UserNotFound()
    return user


async def _current_user(token: UserTokenModel = AccessToken()) -> Optional[User]:
    try:
        return await _require_current_user(token)
    except AuthError:
        return None


def CurrentUser(required: bool = True):  # noqa
    get = _require_current_user
    if not required:
        get = _current_user

    return Depends(get)


class ResourceKey(BaseModel):
    key: str
    resource_type: str

    @classmethod
    def required(cls, allowed_types: Union[List[str], str]):
        if isinstance(allowed_types, str):
            allowed_types = [allowed_types]

        def get_resource_key_dependency(token: Optional[str] = Depends(bearer)):
            if token:
                try:
                    resource_type, _ = parse_resource_key(token)
                except ValueError:
                    raise AuthError("invalid resource key")

                if resource_type not in allowed_types:
                    raise AuthError(
                        "invalid resource key type. allowed resource key types are: "
                        + ", ".join(allowed_types)
                    )
                return cls(key=token, resource_type=resource_type)
            raise AuthError("resource key is missing")

        return get_resource_key_dependency

    @classmethod
    @wraps(required)
    def optional(cls, *args, **kwargs):
        dep = cls.required(*args, **kwargs)

        @wraps(dep)
        def _optional(*a, **kw):
            try:
                return dep(*a, **kw)
            except AuthError:
                return None

        return _optional
