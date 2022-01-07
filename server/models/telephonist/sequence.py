import enum
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from beanie import Document, PydanticObjectId
from pydantic import Field

from server.database import register_model


class EventSequenceState(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"


@register_model
class EventSequence(Document):
    name: str
    app_id: PydanticObjectId
    finished_at: Optional[datetime]
    description: Optional[str]
    meta: Optional[Dict[str, Any]]
    state: EventSequenceState = EventSequenceState.PENDING
    related_task: str

    class Collection:
        name = "event_sequences"
        indexes = ["name", "related_task"]
