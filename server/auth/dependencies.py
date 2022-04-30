from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException
from fastapi.openapi.models import SecurityBase as SecurityBaseModel
from fastapi.security import HTTPBasic, HTTPBearer
from fastapi.security.base import SecurityBase
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import Field
from starlette.requests import Request
from starlette.status import HTTP_403_FORBIDDEN

from server.exceptions import ApiException

from .exceptions import AuthError, UserNotFound
from .models import User, UserSession
from .utils import unmask_hex_token

# region Sessions and CSRF


class CSRFToken:
    def __init__(self, *, safe_methods: list[str], header_name: str):
        self.header = header_name
        self.safe_methods = safe_methods

    def __call__(self, request: Request):
        if request.method in self.safe_methods:
            return None
        token = request.headers.get(self.header)
        if token:
            try:
                return unmask_hex_token(token)
            except:
                pass
        return None


class SessionCookieModel(SecurityBaseModel):
    type_: Literal["apiKey"] = Field(alias="type", default="apiKey")
    in_: Literal["cookie"] = Field(alias="in", default="cookie")
    name: str


class SessionCookie(SecurityBase):
    model: SessionCookieModel

    def __init__(
        self,
        cookie: str,
        *,
        schema_name: str = "SessionCookie",
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        self.scheme_name = schema_name
        self.description = description
        self.auto_error = auto_error
        self.cookie = cookie
        self.model = SessionCookieModel(name=schema_name)

    def __call__(self, request: Request) -> Optional[str]:
        return request.cookies.get(self.cookie)


# endregion

# region Authentication schema


class BearerSchema(HTTPBearer):
    async def __call__(
        self, authorization: Optional[str] = Header(None)
    ) -> Optional[str]:
        if authorization is None:
            return None
        scheme, param = get_authorization_scheme_param(authorization)
        if not authorization or scheme.lower() != "bearer":
            return None
        return param


bearer = BearerSchema()
basic = HTTPBasic(auto_error=False)


def require_bearer(token: Optional[str] = Depends(bearer)):
    if token is None:
        raise ApiException(401, "auth.no_token", "token is missing")
    return token


# endregion


# region Session deps


session_cookie = SessionCookie("APISID")
csrf_token = CSRFToken(
    safe_methods=["GET", "OPTIONS"], header_name="X-CSRF-Token"
)


def require_session_cookie(session_id: str = Depends(session_cookie)):
    if session_id is None:
        raise AuthError(401, "auth.no_session", "Session cookie is missing")
    return session_id


async def get_session(
    session_id: str = Depends(session_cookie),
) -> Optional[UserSession]:
    if session_id is None:
        return None
    return await UserSession.find_one({"_id": session_id})


async def require_session(
    request: Request,
    session_id: str = Depends(require_session_cookie),
) -> UserSession:
    if "app_session" in request.scope:
        return request.scope["app_session"]
    data = await UserSession.find_one({"_id": session_id})
    if data is None:
        raise AuthError(
            401, "auth.no_session", "Invalid or expired session cookie"
        )
    return data


# endregion


# region Current user deps


async def _require_current_user(
    session: UserSession = Depends(require_session),
) -> User:
    user = await User.get(session.user_id)
    if user is None:
        raise UserNotFound()
    return user


async def _current_user(
    session: UserSession = Depends(get_session),
) -> Optional[User]:
    if session:
        try:
            return await _require_current_user(session)
        except AuthError:
            return None
    return None


def CurrentUser(required: bool = True) -> User:  # noqa
    get = _require_current_user
    if not required:
        get = _current_user

    return Depends(get)


def superuser(session: UserSession = Depends(require_session)):
    if not session.is_superuser:
        raise AuthError(401, "You're not a superuser!")
    return session


# endregion


def validate_csrf_token(
    request: Request,
    token: str = Depends(csrf_token),
    session: UserSession = Depends(require_session),
):
    if request.method in ("GET", "OPTIONS", "HEAD"):
        return
    if token is None:
        raise HTTPException(
            HTTP_403_FORBIDDEN, "CSRF token is missing", headers={}
        )
    if token != session.csrf_token:
        raise HTTPException(HTTP_403_FORBIDDEN, "CSRF token mismatch")
