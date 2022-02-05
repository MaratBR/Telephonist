import abc
from typing import TYPE_CHECKING, Optional, Type, TypeVar

from beanie import Document, PydanticObjectId
from fastapi import Depends, HTTPException, Query
from pydantic import validator
from starlette.websockets import WebSocket

from server.internal.auth.exceptions import InvalidToken
from server.internal.auth.token import JWT, TokenModel
from server.internal.channels.wscode import WSC_UNAUTHORIZED


class ConcreteWSTicket(abc.ABC, TokenModel):
    sub: PydanticObjectId
    connection_name: Optional[str]

    @validator("sub")
    def _stringify_sub(cls, value):
        return str(value)


_ws_ticket_cache = {}

if TYPE_CHECKING:
    WSTicketModel = ConcreteWSTicket
else:

    class WSTicketMeta(type):
        def __getitem__(self, item: Type[Document]) -> Type[ConcreteWSTicket]:
            if item not in _ws_ticket_cache:
                _ws_ticket_cache[item] = type(
                    f"WSTicket[{item.__name__}]",
                    (ConcreteWSTicket,),
                    {"__token_type__": f"ws-ticket:{item.__name__}"},
                )
            return _ws_ticket_cache[item]

    class WSTicketModel(metaclass=WSTicketMeta):
        pass


TDoc = TypeVar("TDoc", bound=Document)


def WSTicket(model_class: Type[TDoc]) -> WSTicketModel[TDoc]:
    async def dependency(ws: WebSocket, ticket: str = Query(...)):
        try:
            return JWT[WSTicketModel[model_class]](ticket).model
        except InvalidToken:
            await ws.close(WSC_UNAUTHORIZED)
        except HTTPException:
            await ws.close(1011)

    return Depends(dependency)
