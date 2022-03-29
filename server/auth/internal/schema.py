from typing import Optional

from fastapi import Depends, Header
from fastapi.security import HTTPBasic, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param

from server.auth.internal.exceptions import InvalidToken
from server.common.models import AppBaseModel


class HybridLoginData(AppBaseModel):
    login: str
    password: str
    hybrid: bool = True


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
