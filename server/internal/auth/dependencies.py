import hashlib
from typing import *

from fastapi import Cookie, Depends, params

from server.models.auth import BlockedAccessToken, User

from .exceptions import AuthError, InvalidToken, UserNotFound
from .schema import JWT_CHECK_HASH_COOKIE, bearer, require_bearer
from .token import TokenModel, UserTokenModel


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
) -> Union[params.Depends, UserTokenModel]:
    return Depends(_require_user_token if required else _get_user_token)


def Token(token_model: Type[TokenModel], required: bool = True):  # noqa: N802
    if required:

        def dependency_function(token: Optional[str] = Depends(bearer)):
            return token_model.decode(token)

    else:

        def dependency_function(token: Optional[str] = Depends(bearer)):
            try:
                return token_model.decode(token)
            except AuthError:
                return None

    return Depends(dependency_function)


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
