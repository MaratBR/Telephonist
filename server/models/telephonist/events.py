import enum
from typing import Any, Optional

from beanie import Document, Indexed, PydanticObjectId

from server.database import register_model


class EventSource(str, enum.Enum):
    USER = "user"
    APPLICATION = "app"
    UNKNOWN = "?"


@register_model
class Event(Document):
    source_type: EventSource = EventSource.UNKNOWN
    source_id: Optional[PydanticObjectId]
    event_type: Indexed(str)
    related_task: Optional[str]
    data: Optional[Any] = None
    publisher_ip: Optional[str]

    class Collection:
        name = "events"
        indexes = ["related_task_type"]

    @classmethod
    def by_type(cls, event_type: str):
        return cls.find(cls.event_type == event_type.lower())

    @classmethod
    def by_task_name(cls, task_name: str):
        return cls.find(cls.related_task == task_name)

    @classmethod
    def custom_events(cls):
        return cls.find({"related_task_type": None})
