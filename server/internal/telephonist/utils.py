from typing import Optional, TypeVar, Union

from beanie import PydanticObjectId
from fastapi import HTTPException
from starlette import status

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
    def event(cls, name: str):
        return cls.EVENTS + ".byName." + name

    @classmethod
    def task_events(cls, task_name: str):
        return cls.EVENTS + ".byTask." + task_name

    @classmethod
    def app_events(cls, app_id: Union[str, PydanticObjectId]):
        return cls.APPS + "." + str(app_id) + ".events"
