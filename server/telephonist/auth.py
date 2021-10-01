from typing import Optional

from fastapi import Depends

from server.auth.models import User
from server.auth.utils import require_bearer, current_user


class TelephonistAuth:
    def __init__(
            self,
            token: str = Depends(require_bearer),
            user: Optional[User] = Depends(current_user)
    ):
        self.user = user
        self.token = token

