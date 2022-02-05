import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from server.database import register_model
from server.settings import settings

_logger = logging.getLogger("telephonist.database")


class StatusEntry(BaseModel):
    progress: Optional[int]
    tasks_total: Optional[int]
    is_intermediate: bool = False
    title: Optional[str]
    subtitle: Optional[str]
    task_name: Optional[str]


@register_model
class ConnectionInfo(Document):
    id: UUID = Field(default_factory=uuid4)
    ip: str
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    disconnected_at: Optional[datetime]
    expires_at: Optional[datetime]
    client_name: Optional[str]
    client_version: Optional[str]
    app_id: PydanticObjectId
    fingerprint: str
    os: str
    instance_id: Optional[UUID]
    machine_id: Optional[str]
    is_connected: bool = False
    event_subscriptions: List[str] = Field(default_factory=list)
    bound_sequences: List[PydanticObjectId] = Field(default_factory=list)

    @classmethod
    async def on_database_ready(cls):
        query = ConnectionInfo.find({"is_connected": True})
        hanging_connections = await query.count()
        if hanging_connections > 0:
            _logger.warning(
                "There's %d hanging connections in the database, this means that either"
                " there's more than 1 instance of Telephonist running with this database or"
                " Telephonist exited unexpectedly",
                hanging_connections,
            )
            if settings.hanging_connections_policy == "remove":
                _logger.warning(
                    'settings.hanging_connections_policy is set to "remove", all hanging'
                    " connections will be removed"
                )
                await query.delete()

    class Settings:
        use_state_management = True
        use_revision = True

    class Collection:
        indexes = [pymongo.IndexModel("expires_at", name="expires_at_ttl", expireAfterSeconds=1)]
