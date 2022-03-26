from datetime import datetime
from typing import Optional

from beanie import PydanticObjectId
from fastapi import Depends, Header
from fastapi.security import HTTPBasic, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from starlette.responses import JSONResponse

from server.auth.internal.exceptions import InvalidToken
from server.common.models import AppBaseModel
from server.settings import settings

JWT_CHECK_HASH_COOKIE = "chk"
JWT_REFRESH_COOKIE = "jwt.refresh"


class HybridLoginData(AppBaseModel):
    login: str
    password: str
    hybrid: bool = True


class TokenResponse(JSONResponse):
    def __init__(
        self,
        user_id: PydanticObjectId,
        token: Optional[str],
        refresh_token: Optional[str],
        password_reset_token: str = None,
        refresh_cookie_path: Optional[str] = None,
        refresh_as_cookie: bool = False,
        check_string: Optional[str] = None,
        token_exp: Optional[datetime] = None,
    ):
        super(TokenResponse, self).__init__(
            {
                "user_id": str(user_id),
                "access_token": token,
                "exp": token_exp.isoformat() if token_exp else None,
                "refresh_token": None if refresh_as_cookie else refresh_token,
                "token_type": "bearer",
                "password_reset_required": password_reset_token is not None,
                "password_reset_token": password_reset_token
                if password_reset_token
                else None,
            }
        )

        if refresh_as_cookie and refresh_token:
            self.set_cookie(
                JWT_REFRESH_COOKIE,
                refresh_token,
                path=refresh_cookie_path,
                httponly=True,
                max_age=settings.refresh_token_lifetime.total_seconds(),
                secure=settings.cookies_policy.lower() == "none",
                samesite=settings.cookies_policy,
            )

        if check_string:
            self.set_cookie(
                JWT_CHECK_HASH_COOKIE,
                check_string,
                httponly=True,
                max_age=settings.refresh_token_lifetime.total_seconds(),
                secure=settings.cookies_policy.lower() == "none",
                samesite=settings.cookies_policy,
            )


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
        raise InvalidToken("token is missing")
    return token
