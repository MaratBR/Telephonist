import enum
from typing import Any, Optional

from beanie import Document, Indexed, PydanticObjectId

from server.database import register_model


@register_model
class Event(Document):
    app_id: PydanticObjectId
    event_key: str
    event_type: str
    related_task: Optional[str]
    data: Optional[Any] = None
    publisher_ip: Optional[str]
    sequence_id: Optional[PydanticObjectId]

    class Collection:
        name = "events"
        indexes = [
            "related_task",
            "sequence_id",
            "event_type",
            "event_key",
            "publisher_ip",
            "app_id",
        ]

    @classmethod
    def by_type(cls, event_type: str):
        return cls.find(cls.event_type == event_type.lower())

    @classmethod
    def by_task_name(cls, task_name: str):
        return cls.find(cls.related_task == task_name)

    @classmethod
    def custom_events(cls):
        return cls.find({"related_task_type": None})
