import time
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from beanie import PydanticObjectId
from pydantic import Field

from server.common.models import BaseDocument, convert_to_utc
from server.database.registry import register_model


@register_model
class Event(BaseDocument):
    app_id: PydanticObjectId
    task_name: Optional[str]
    task_id: Optional[UUID]
    sequence_id: Optional[PydanticObjectId]
    event_key: str
    event_type: str
    t: int = Field(default_factory=lambda: time.time_ns() // 1000)
    data: Optional[Any] = None
    publisher_ip: Optional[str]

    class Config:
        json_encoders = {
            datetime: lambda dt: None
            if dt is None
            else convert_to_utc(dt).isoformat()
        }

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
