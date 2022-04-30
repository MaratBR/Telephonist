import hashlib
import json
import logging
from datetime import datetime
from typing import Awaitable, List, Optional, Union, cast
from uuid import UUID, uuid4

from beanie import PydanticObjectId
from pydantic import Field, validator
from pymongo.client_session import ClientSession

from server.common.models import AppBaseModel, BaseDocument, convert_to_utc
from server.database.registry import register_model
from server.settings import settings

_logger = logging.getLogger("telephonist.database")


class ApplicationClientInfo(AppBaseModel):
    name: str
    version: str
    compatibility_key: str
    os_info: str
    connection_uuid: UUID
    machine_id: str = Field(max_length=200)
    instance_id: Optional[UUID]

    def get_fingerprint(self):
        return hashlib.sha256(
            json.dumps(
                [1, self.name, self.compatibility_key]
            ).encode()  # 1 - fingerprint version
        ).hexdigest()


@register_model
class ConnectionInfo(BaseDocument):
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

    _at_validator = validator(
        "connected_at", "disconnected_at", allow_reuse=True
    )(convert_to_utc)

    @classmethod
    def get(
        cls,
        document_id: UUID,
        session: Optional[ClientSession] = None,
        ignore_cache: bool = False,
        fetch_links: bool = False,
    ) -> Awaitable["ConnectionInfo"]:
        return super(ConnectionInfo, cls).get(
            cast(PydanticObjectId, document_id),
            session,
            ignore_cache,
            fetch_links,
        )

    @classmethod
    async def remove_subscription(
        cls,
        connection_id: UUID,
        events: Union[str, list[str], tuple[str], set[str]],
    ):
        if isinstance(events, str):
            events = [events]
        else:
            events = list(events)

        await cls.find({"_id": connection_id}).update(
            {
                "$pull": {
                    "event_subscriptions": events[0]
                    if len(events) == 1
                    else {"$each": events}
                }
            }
        )

    @classmethod
    async def add_subscription(
        cls,
        connection_id: UUID,
        events: Union[str, list[str], tuple[str], set[str]],
    ):
        if isinstance(events, str):
            events = [events]
        else:
            events = list(events)
        await cls.find({"_id": connection_id}).update(
            {
                "$addToSet": {
                    "event_subscriptions": events[0]
                    if len(events) == 1
                    else {"$each": events}
                }
            }
        )

    @classmethod
    async def find_or_create(
        cls,
        app_id: PydanticObjectId,
        info: ApplicationClientInfo,
        ip_address: str,
    ):
        connection = await cls.find_one(
            ConnectionInfo.id == info.connection_uuid
        )

        if connection is None:
            connection = ConnectionInfo(
                id=info.connection_uuid,
                ip=ip_address,
                client_name=info.name,
                client_version=info.version,
                app_id=app_id,
                fingerprint=info.get_fingerprint(),
                os=info.os_info,
                is_connected=True,
                machine_id=info.machine_id,
                instance_id=info.instance_id,
            )
            await connection.insert()
        else:
            connection.connected_at = datetime.utcnow()
            connection.is_connected = True
            connection.machine_id = info.machine_id
            connection.instance_id = info.instance_id
            connection.os = info.os_info
            connection.app_id = app_id
            connection.client_name = info.name
            connection.client_version = info.version
            connection.fingerprint = info.get_fingerprint()
            connection.ip = ip_address
            await connection.save_changes()
        return connection

    @classmethod
    async def on_database_ready(cls):
        query = ConnectionInfo.find({"is_connected": True})
        hanging_connections = await query.count()
        if hanging_connections > 0:
            _logger.warning(
                "There's %d hanging connections in the database, this means"
                " that either there's more than 1 instance of Telephonist"
                " running with this database or Telephonist exited"
                " unexpectedly",
                hanging_connections,
            )
            if settings.get().hanging_connections_policy == "remove":
                _logger.warning(
                    'settings.hanging_connections_policy is set to "remove",'
                    " all hanging connections will be removed"
                )
                await query.delete()

    class Settings:
        use_state_management = True
        use_revision = True

    class Collection:
        indexes = []
