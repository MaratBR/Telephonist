import hashlib
from typing import *

from fastapi import Cookie, Depends
from jose import JWTError
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from server.internal.auth.exceptions import AuthError, InvalidToken, UserNotFound
from server.internal.auth.schema import JWT_CHECK_HASH_COOKIE, bearer
from server.models.auth import BlockedAccessToken, TokenModel, User
from server.settings import settings


def require_bearer(token: Optional[str] = Depends(bearer)):
    if token is None:
        raise InvalidToken("token is missing")
    return token


def _require_jwt_token(
    check_string: Optional[str] = Cookie(None, alias=JWT_CHECK_HASH_COOKIE),
    jwt: str = Depends(require_bearer),
):
    token = parse_jwt_token(jwt)
    if token.check_string:
        if (
            check_string is None
            or token.check_string != hashlib.sha256(check_string.encode()).hexdigest()
        ):
            raise InvalidToken(
                f'jwt token check string is invalid or check string cookie ("{JWT_CHECK_HASH_COOKIE}) is missing'
            )
    return token


def _get_jwt_token(
    check_string: Optional[str] = Cookie(None, alias=JWT_CHECK_HASH_COOKIE),
    jwt: str = Depends(bearer),
):
    if jwt is None:
        return None
    try:
        return _require_jwt_token(check_string, jwt)
    except InvalidToken:
        return None


def Token(required: bool = True):  # noqa N802
    return Depends(_require_jwt_token if required else _get_jwt_token)


def parse_jwt_token(token: str) -> TokenModel:
    try:
        return TokenModel.decode(token)
    except JWTError as exc:
        raise InvalidToken("invalid jwt token: " + str(exc), exc)
    except ValidationError as exc:
        raise InvalidToken("invalid token data structure: " + str(exc), exc)


def get_token_dependency_function(  # noqa N802
    token_type: Optional[Union[str, Set[str]]] = None,
    required: bool = True,
):
    if isinstance(token_type, str) and token_type in (None, "access"):
        token_type: Set[str] = {token_type}

    async def get_token_dependency(
        request: Request, token: TokenModel = Token(required=required)
    ):
        if token_type and token.token_type not in token_type:
            allowed_token_types = ", ".join(map(lambda v: f'"{v}"', token_type))
            raise InvalidToken(
                f'token type "{token.token_type}" is not allowed, '
                f"only token types that're allowed are: {allowed_token_types}"
            )

        if token.check_string:
            check_string = request.cookies.get(settings.jwt_secret)

        return token

    if not required:
        require_token_dep = get_token_dependency

        def get_token_dependency(token: TokenModel = Token()):
            try:
                return require_token_dep(token)
            except InvalidToken:
                return None

    return get_token_dependency


def UserToken(  # noqa N802
    token_type: Optional[Union[str, Set[str]]] = None,
    required: bool = True,
):
    return Depends(get_token_dependency_function(token_type, required))


async def _require_current_user(token: TokenModel = UserToken()) -> User:
    if await BlockedAccessToken.is_blocked(token.jti):
        raise AuthError("This token has been revoked")
    user = await User.get(token.sub)
    if user is None:
        raise UserNotFound()
    return user


async def _current_user(token: TokenModel = UserToken()) -> Optional[User]:
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
    resource_type: Optional[str]
    resource_key: str

    @classmethod
    def Depends(
        cls, *resource_types: str, required: bool = True
    ) -> "ResourceKey":  # noqa
        if "*" in resource_types:
            resource_types = ("*",)

        def _get_resource_key(token: Optional[str] = Depends(bearer)):
            try:
                if token is None:
                    raise InvalidToken("resource key is missing")
                else:
                    if "." in token:
                        resource_type = token.split(".")[0]
                    else:
                        resource_type = None
                    if (
                        "*" not in resource_types
                        and resource_type not in resource_types
                    ):
                        raise InvalidToken("resource key is of the wrong type")
                return cls(resource_type=resource_type, resource_key=token)
            except (InvalidToken, ValidationError, ValueError) as exc:
                if required:
                    if isinstance(exc, ValidationError):
                        exc = InvalidToken("failed to validate resource key", exc)
                    raise exc
                else:
                    return None

        return Depends(_get_resource_key)
