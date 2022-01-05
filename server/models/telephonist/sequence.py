from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from beanie import Document, PydanticObjectId
from pydantic import Field

from server.database import register_model


@register_model
class EventSequence(Document):
    name: Optional[str]
    app_id: Optional[PydanticObjectId]
    finished_at: Optional[datetime]

    class Collection:
        name = "event_sequences"
