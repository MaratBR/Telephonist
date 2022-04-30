from typing import Optional

from server.exceptions import ApiException


class AuthError(ApiException):
    pass


class InvalidToken(AuthError):
    def __init__(self, message: Optional[str] = None):
        super(InvalidToken, self).__init__(
            401, "auth.invalid_token", message or "Invalid token"
        )


class UserNotFound(AuthError):
    def __init__(self, user: Optional[str] = None):
        super(UserNotFound, self).__init__(
            401,
            "auth.user_not_found",
            f"User '{user}' not found" if user else "User not found",
        )
