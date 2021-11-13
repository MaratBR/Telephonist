from datetime import timedelta
from typing import Optional, Type, TypeVar, List, Set, Union

from beanie import Document
from fastapi import HTTPException, Depends, Header, Cookie
from fastapi.openapi.models import HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError
from pydantic import ValidationError, BaseModel
from starlette import status
from starlette.responses import JSONResponse

from server.auth.hash import verify_password
from server.auth.models import BlockedAccessToken, TokenModel, User, token_subjects_registry
from server.auth.tokens import decode_token
from server.settings import settings


class AuthError(HTTPException):
    def __init__(self, message: str, inner: Optional[Exception] = None,
                 status_code: int = status.HTTP_401_UNAUTHORIZED):
        super(AuthError, self).__init__(status_code, message)
        self.inner = inner


class InvalidToken(AuthError):
    pass


class UserNotFound(AuthError):
    def __init__(self):
        super(UserNotFound, self).__init__('user not found', status_code=404)


JWT_SIGNATURE_COOKIE = 'jwt.sig'
JWT_REFRESH_COOKIE = 'jwt.refresh'


class HybridLoginData(BaseModel):
    login: str
    password: str
    hybrid: bool = False
    scope: List[str]


class TokenResponse(JSONResponse):
    def __init__(self,
                 token: TokenModel,
                 refresh_token: Optional[str],
                 hybrid: bool,
                 refresh_cookie_path: Optional[str] = None):
        if hybrid:
            token = token.encode()
            token, signature = token.rsplit('.', 1)
        else:
            token = token.encode()
            signature = None

        if refresh_token:
            refresh_token = refresh_token.encode()
        super(TokenResponse, self).__init__({
            'access_token': token,
            'refresh_token': None if hybrid else refresh_token,
            'token_type': 'hybrid-bearer' if hybrid else 'bearer',
        })

        if hybrid:
            if refresh_token:
                self.set_cookie(JWT_REFRESH_COOKIE, refresh_token,
                                httponly=True, max_age=settings.refresh_token_lifetime.total_seconds())

            self.set_cookie(JWT_SIGNATURE_COOKIE, signature,
                            httponly=True, max_age=settings.refresh_token_lifetime.total_seconds(),
                            path=refresh_cookie_path)


class HybridBearerSchema(HTTPBearer):
    async def __call__(self,
                       jwt_signature: Optional[str] = Cookie(None, alias=JWT_SIGNATURE_COOKIE),
                       authorization: Optional[str] = Header(None)) -> Optional[str]:
        if authorization is None:
            return None
        scheme, param = get_authorization_scheme_param(authorization)
        if not authorization or scheme.lower() != "bearer":
            return None

        if jwt_signature is not None and len(jwt_signature) > 0:
            return param + '.' + jwt_signature

        return param


bearer = HybridBearerSchema()


def require_bearer(token: Optional[str] = Depends(bearer)):
    if token is None:
        raise InvalidToken('token is missing')
    return token


TTokenModel = TypeVar('TTokenModel', bound=TokenModel)


def parse_token(token: str) -> TokenModel:
    """
    Парсит токен и возращает соответсвующий ему класс..
    :param token: JWT токен
    :return: модель данных токена
    """
    try:
        return TokenModel(**decode_token(token))
    except JWTError as exc:
        raise InvalidToken('invalid jwt token', exc)
    except ValidationError as exc:
        raise InvalidToken('invalid token data structure or invalid/unknown token type', exc)


def _get_token(jwt: str = Depends(require_bearer)):
    return parse_token(jwt)


def Token():  # noqa N802
    return Depends(_get_token)


def get_token_dependency_function(  # noqa N802
        token_type: Optional[Union[str, Set[str]]] = None,
        subject: Optional[Union[str, Type[Document], Set[Union[str, Type[Document]]]]] = None,
        required: bool = True,
):
    if subject:
        subject = token_subjects_registry.expand_names(subject)
    if isinstance(token_type, str):
        token_type: Set[str] = {token_type}

    async def get_token_dependency(token: TokenModel = Token()):
        if token_type and token.token_type not in token_type:
            allowed_token_types = ', '.join(map(lambda v: f'"{v}"', token_type))
            raise InvalidToken(
                f'token type "{token.token_type}" is not allowed, '
                f'only token types that\'re allowed are: {allowed_token_types}')

        if subject and token.sub.type_name not in subject:
            allowed_subject_types = ', '.join(map(lambda v: f'"{v}"', subject))
            raise InvalidToken(f'Invalid subject type, allowed subject types: {allowed_subject_types}')

        return token

    if not required:
        require_token_dep = get_token_dependency

        def get_token_dependency(token: TokenModel = Token()):
            try:
                return require_token_dep(token)
            except InvalidToken:
                return None

    return get_token_dependency


def TokenDependency(  # noqa N802
        token_type: Optional[Union[str, Set[str]]] = None,
        subject: Optional[Union[str, Type[Document], Set[Union[str, Type[Document]]]]] = None,
        required: bool = True,
):
    return Depends(get_token_dependency_function(token_type, subject, required))


def UserToken(required: bool = True):  # noqa
    return TokenDependency(token_type='access', subject=User, required=required)


async def _require_current_user(
        token: TokenModel = UserToken()
) -> User:
    if await BlockedAccessToken.is_blocked(token.jti):
        raise AuthError('This token has been revoked')
    user = await User.get(token.sub.oid)
    if user is None:
        raise UserNotFound()
    return user


async def _current_user(
        token: TokenModel = UserToken()
) -> Optional[User]:
    try:
        return await _require_current_user(token)
    except AuthError:
        return None


def CurrentUser(required: bool = True):  # noqa
    get = _require_current_user
    if not required:
        get = _current_user

    return Depends(get)


# region Login and token generation


async def find_user_by_credentials(username: str, password: str):
    user = await User.by_username(username)
    if user is not None:
        if verify_password(password, user.password_hash):
            return user
    return None


def create_access_token(user: User, lifetime: Optional[timedelta] = None, scopes: Optional[List[str]] = None) -> str:
    return user.create_token(
        scope=set(scopes) if scopes else None,
        lifetime=lifetime
    ).encode()

# endregion
