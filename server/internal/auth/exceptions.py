from typing import Optional

from fastapi import HTTPException
from starlette import status


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
