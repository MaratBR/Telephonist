from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from server.database import register_model


@register_model
class Event(Document):
    app_id: PydanticObjectId
    task_name: Optional[str]
    task_id: Optional[PydanticObjectId]
    sequence_id: Optional[PydanticObjectId]
    event_key: str
    event_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[Any] = None
    publisher_ip: Optional[str]

    class Collection:
        name = "events"
        indexes = [
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
        return cls.find(cls.task_name == task_name)
