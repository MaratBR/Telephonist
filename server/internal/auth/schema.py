from typing import Optional

from fastapi import Header
from fastapi.security import HTTPBasic, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from pydantic import BaseModel
from starlette.responses import JSONResponse

from server.models.auth import TokenModel
from server.settings import settings

JWT_CHECK_HASH_COOKIE = "chk"
JWT_REFRESH_COOKIE = "jwt.refresh"


class HybridLoginData(BaseModel):
    login: str
    password: str
    hybrid: bool = False


class TokenResponse(JSONResponse):
    def __init__(
        self,
        token: Optional[TokenModel],
        refresh_token: Optional[str],
        password_reset_token: Optional[TokenModel] = None,
        refresh_cookie_path: Optional[str] = None,
        refresh_as_cookie: bool = False,
        check_string: Optional[str] = None,
    ):
        signature = None
        if token:
            token = token.encode()

        super(TokenResponse, self).__init__(
            {
                "access_token": token,
                "refresh_token": None if refresh_as_cookie else refresh_token,
                "token_type": "bearer",
                "password_reset_required": password_reset_token is not None,
                "password_reset_token": password_reset_token.encode()
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
            )

        if check_string:
            self.set_cookie(
                JWT_CHECK_HASH_COOKIE,
                check_string,
                httponly=True,
                max_age=settings.refresh_token_lifetime.total_seconds(),
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
