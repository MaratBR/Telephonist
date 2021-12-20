from datetime import timedelta

from fastapi import HTTPException
from server.routes.telephonist._router import router
from starlette import status

from server.internal.auth.dependencies import TokenDependency
from server.internal.auth.utils import create_ws_ticket
from server.models.auth import TokenModel


@router.get('/ws-ticket')
async def get_ws_ticket(token: TokenModel = TokenDependency(token_type='access')):
    subject = await token.subject.type.get(token.subject.oid)
    if subject is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    return {'ticket': create_ws_ticket(subject, timedelta(hours=12))}
