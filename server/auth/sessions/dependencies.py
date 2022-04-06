from typing import Literal, Optional

from fastapi.openapi.models import SecurityBase as SecurityBaseModel
from fastapi.security.base import SecurityBase
from pydantic import Field
from starlette.requests import Request

from server.auth.sessions.utils import unmask_token


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
                return unmask_token(token)
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
