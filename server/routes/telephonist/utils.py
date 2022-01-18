from fastapi import Depends
from starlette.exceptions import HTTPException

from server.internal.auth.schema import require_bearer
from server.models.telephonist import Application


async def get_application_from_key(token: str = Depends(require_bearer)):
    app = await Application.find_by_key(token)
    if app is None:
        raise HTTPException(401, "Could not identify the application using provided access key")
    return app
