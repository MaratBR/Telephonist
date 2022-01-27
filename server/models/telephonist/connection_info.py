from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import pymongo
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field

from server.database import register_model
from server.settings import settings


class StatusEntry(BaseModel):
    progress: Optional[int]
    tasks_total: Optional[int]
    is_intermediate: bool = False
    title: Optional[str]
    subtitle: Optional[str]
    related_task: Optional[str]


@register_model
class ConnectionInfo(Document):
    ip: str
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    disconnected_at: Optional[datetime]
    expires_at: Optional[datetime]
    client_name: Optional[str]
    client_version: Optional[str]
    app_id: PydanticObjectId
    os: str
    instance_id: str
    machine_id: str
    is_connected: bool = False
    event_subscriptions: List[str] = Field(default_factory=list)

    @classmethod
    async def on_database_ready(cls):
        query = ConnectionInfo.find({"is_connected": True})
        hanging_connections = await query.count()
        if hanging_connections > 0:
            logger.warning(
                "There's {count} hanging connections in the database, this means that either"
                " there's more than 1 instance of Telephonist running with this database or"
                " Telephonist exited unexpectedly",
                count=hanging_connections,
            )
            if settings.hanging_connections_policy == "remove":
                logger.warning(
                    'settings.hanging_connections_policy is set to "remove", all hanging'
                    " connections will be removed"
                )
                await query.delete()

    class Settings:
        use_state_management = True
        use_revision = True

    class Collection:
        indexes = [pymongo.IndexModel("expires_at", name="expires_at_ttl", expireAfterSeconds=1)]
