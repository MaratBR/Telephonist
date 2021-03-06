import enum
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from beanie import PydanticObjectId
from pydantic import Field, validator

from server.common.models import AppBaseModel, BaseDocument, convert_to_utc
from server.database.registry import register_model


class EventSequenceState(str, enum.Enum):
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"
    FROZEN = "frozen"
    ORPHANED = "orphan"

    @property
    def is_finished(self):
        return self in [
            EventSequenceState.FAILED,
            EventSequenceState.SUCCEEDED,
            EventSequenceState.SKIPPED,
        ]


class TriggeredBy(AppBaseModel):
    trigger_type: str
    trigger_body: Optional[Any]
    extra: Optional[dict[str, Any]]


@register_model
class EventSequence(BaseDocument):
    name: str
    app_id: PydanticObjectId
    finished_at: Optional[datetime]
    description: Optional[str]
    meta: Optional[dict[str, Any]]
    state: EventSequenceState = EventSequenceState.IN_PROGRESS
    state_updated_at: Optional[datetime]
    task_name: str  # fully qualified task name (application/task_name)
    task_id: UUID
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(days=3)
    )
    error: Optional[str] = None
    connection_id: Optional[UUID]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    triggered_by: Optional[TriggeredBy]
    _created_at_validator = validator("created_at", allow_reuse=True)(
        convert_to_utc
    )

    async def update_meta(self, meta: dict[str, Any]):
        await self.update({"$set": {"meta": meta}})

    class Collection:
        name = "event_sequences"
        indexes = ["name", "task_name", "app_id", "frozen", "state"]

    class Settings:
        use_state_management = True
