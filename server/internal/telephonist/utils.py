from typing import Optional, Type, TypeVar, Union

from beanie import Document, PydanticObjectId
from fastapi import HTTPException
from starlette import status

from server.models.common import SoftDeletes

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


class ChannelGroups:
    EVENTS = "E"
    APPS = "apps"
    GLOBAL_EVENTS = EVENTS + ".GLOBAL"
    ENTRY_UPDATE = "entry"

    @classmethod
    def _g(cls, *parts):
        return "/" + "/".join(str(p) for p in parts)

    @classmethod
    def entry(cls, entry_type, entry_id):
        return cls._g("entry_update", entry_type, entry_id)

    @classmethod
    def events(cls, task_name: Optional[str] = "*", event_type: Optional[str] = "*"):
        return cls._g("events", task_name or "_", event_type or "_")

    @classmethod
    def application_events(cls, app_id: PydanticObjectId):
        return cls._g("application_events", app_id)

    @classmethod
    def app(cls, app_id: Union[str, PydanticObjectId]):
        return cls._g("apps", app_id)

    @classmethod
    def sequence_events(cls, sequence_id: PydanticObjectId):
        return cls._g("sequence_events", sequence_id)

    @classmethod
    def user(cls, user_id: PydanticObjectId):
        return cls._g("users", user_id)


CG = ChannelGroups


async def require_model_with_id(model: Type[Document], document_id, *, message: str = "Not found"):
    if issubclass(model, SoftDeletes):
        q = model.not_deleted()
    else:
        q = model
    Errors.raise404_if_false(await q.find({"_id": document_id}).exists(), message=message)
