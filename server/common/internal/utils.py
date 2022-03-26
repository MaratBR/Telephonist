from typing import Optional, Type, TypeVar

from beanie import Document
from fastapi import HTTPException
from starlette import status

from server.common.models import SoftDeletes

T = TypeVar("T")


class Errors:
    @staticmethod
    def raise404_if_none(value: Optional[T], message: str = "Not found") -> T:
        if value is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, message)
        return value

    @staticmethod
    def raise404_if_false(value: bool, message: str = "Not found"):
        if not value:
            raise HTTPException(status.HTTP_404_NOT_FOUND, message)


class Prefix(str):
    def __truediv__(self, other):
        return Prefix(str(self) + "/" + str(other))

    def is_parent_of(self, prefix):
        return str(prefix).startswith(str(self) + "/")


class ChannelGroups:
    MONITORING = Prefix("monitoring")
    AUTH = Prefix("auth")
    APPLICATION = Prefix("application")
    EVENTS = Prefix("events")


CG = ChannelGroups()


async def require_model_with_id(
    model: Type[Document], document_id, *, message: str = "Not found"
):
    if issubclass(model, SoftDeletes):
        q = model.not_deleted()
    else:
        q = model
    Errors.raise404_if_false(
        await q.find({"_id": document_id}).exists(), message=message
    )
