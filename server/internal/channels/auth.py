import abc
from typing import TYPE_CHECKING, Protocol, Type, TypeVar

from beanie import Document, PydanticObjectId
from fastapi import Depends, Query
from pydantic import validator

from server.internal.auth.token import JWT, TokenModel
from server.models.auth import User


class ConcreteWSTicket(abc.ABC, TokenModel):
    sub: PydanticObjectId

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


def WSTicket(model_class: Type[Document]):
    jwt_type = JWT[WSTicketModel[model_class]]

    def dependency(ticket: str = Query(...)):
        return jwt_type(ticket).model

    return Depends(dependency)
