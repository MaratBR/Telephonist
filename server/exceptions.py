from typing import Optional

from fastapi import HTTPException


class ApiException(HTTPException):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        description: Optional[str] = None,
    ):
        super(ApiException, self).__init__(
            status_code,
            {
                "error": {
                    "code": error_code,
                    "description": description,
                    "type": type(self).__name__,
                }
            },
        )
