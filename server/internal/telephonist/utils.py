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
    def entry(cls, entry_type: str, entry_id: str):
        return cls.ENTRY_UPDATE + "." + entry_type + "." + entry_id

    @classmethod
    def for_event_type(cls, name: str):
        return cls.EVENTS + ".byName." + name

    @classmethod
    def for_task_event(cls, task_name: str):
        return cls.EVENTS + ".byTask." + task_name

    @classmethod
    def for_event_key(cls, event_key: str):
        return cls.EVENTS + ".byKey." + event_key

    @classmethod
    def for_events(
        cls,
        app_id: Optional[Union[str, PydanticObjectId]] = None,
        event_type: Optional[Union[str, Identifier]] = None,
    ):
        app_id = str(app_id) if app_id else "*"
        event_type = str(event_type) if event_type else "*"
        return f"{cls.APPS}.{app_id}.events.{event_type}"

    @classmethod
    def public_app(cls, app_id: Union[str, PydanticObjectId]):
        return cls.APPS + "." + str(app_id) + ".public"

    @classmethod
    def private_app(cls, app_id: Union[str, PydanticObjectId]):
        return cls.APPS + "." + str(app_id) + ".private"


async def trigger_entry_update(entry_type: str, entry_id: str, data: Any):
    entry_id = str(doc.id)
    entry_type = type(doc).__name__
    key = f"{entry_type}.{entry_id}"
    await get_channel_layer().groups_send(
        [ChannelGroups.entry(entry_type, entry_id)],
        "entry_update",
        {"entry_type": entry_type, "id": entry_id, "key": key, "entry": doc},
    )
