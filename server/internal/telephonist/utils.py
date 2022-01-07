from typing import Any, Optional, TypeVar, Union

from beanie import Document, PydanticObjectId
from fastapi import HTTPException
from starlette import status

from server.internal.channels import get_channel_layer
from server.models.common import Identifier

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
        return "/" + "/".join(parts)

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


CG = ChannelGroups
