from typing import TYPE_CHECKING, Optional, Type, TypeVar

from beanie import Document, PydanticObjectId
from fastapi import Depends, HTTPException, Query
from starlette.websockets import WebSocket

from server.auth.exceptions import InvalidToken
from server.auth.services import TokenService
from server.auth.token import TokenModel
from server.common.channels.wscode import WSC_UNAUTHORIZED


class ConcreteWSTicket(TokenModel):
    sub: PydanticObjectId
    connection_name: Optional[str]

    def token_dict(self):
        d = super(ConcreteWSTicket, self).token_dict()
        d["sub"] = str(d["sub"])
        return d


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
    async def dependency(
        ws: WebSocket,
        ticket: str = Query(...),
        token_service: TokenService = Depends(),
    ):
        try:
            return token_service.decode(WSTicketModel[model_class], ticket)
        except InvalidToken:
            await ws.close(WSC_UNAUTHORIZED)
        except HTTPException:
            await ws.close(1011)

    return Depends(dependency)
