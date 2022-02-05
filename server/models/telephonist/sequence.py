import enum
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from beanie import Document, PydanticObjectId
from pydantic import Field

from server.database import register_model


class EventSequenceState(str, enum.Enum):
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"

    @property
    def is_finished(self):
        return self in [
            EventSequenceState.FAILED,
            EventSequenceState.SUCCEEDED,
            EventSequenceState.SKIPPED,
        ]


@register_model
class EventSequence(Document):
    name: str
    app_id: PydanticObjectId
    finished_at: Optional[datetime]
    description: Optional[str]
    meta: Optional[Dict[str, Any]]
    state: EventSequenceState = EventSequenceState.IN_PROGRESS
    task_name: Optional[str]
    task_id: Optional[UUID]
    expires_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=3))
    frozen: bool = False
    error: Optional[str] = None
    connection_id: Optional[UUID]

    class Collection:
        name = "event_sequences"
        indexes = ["name", "task_name", "app_id", "frozen", "state"]

    class Settings:
        use_state_management = True
