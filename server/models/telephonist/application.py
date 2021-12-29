import asyncio
import enum
from datetime import datetime
from typing import *

import pymongo
from beanie import Document, Indexed, PydanticObjectId
from beanie.operators import Inc
from beanie.operators import Set as SetOp
from pydantic import BaseModel, Field

from server.database import register_model
from server.internal.auth.utils import static_key_factory
from server.models.common import IdProjection


class ProcessType(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    FINISHING = "finishing"
    INITIALIZATION = "initialization"
    COMPLETED = "completed"


class ProcessEntry(BaseModel):
    title: Optional[str]
    subtitle: Optional[str]
    type: ProcessType
    progress: Optional[int]
    started_at: Optional[datetime]
    connection_id: str
    id: str


@register_model
class ConnectionInfo(Document):
    internal_id: Indexed(str, unique=True)
    ip: str
    connected_at: datetime = Field(default_factory=datetime.now)
    disconnected_at: Optional[datetime]
    expires_at: Optional[datetime]
    client_name: Optional[str]
    app_id: PydanticObjectId
    is_connected: bool = False
    event_subscriptions: List[str] = Field(default_factory=list)
    processes: List[ProcessEntry] = Field(default_factory=list)

    class Settings:
        use_state_management = True
        use_revision = True

    class Collection:
        indexes = [
            pymongo.IndexModel(
                "expires_at", name="expires_at_ttl", expireAfterSeconds=1
            )
        ]


@register_model
class Application(Document):
    name: Indexed(str, unique=True)
    description: Optional[str] = None
    disabled: bool = False
    settings: Optional[Any]
    settings_type: Optional[str]
    settings_schema: Optional[Any]
    tags: List[str] = Field(default_factory=list)
    access_key: str = Field(default_factory=static_key_factory(key_type="application"))

    @property
    def has_connection(self):
        return len(self.connection_info) > 0

    async def add_subscription(self, event_type: str):
        if any(sub.event_type == event_type for sub in self.event_subscriptions):
            return
        self.event_subscriptions.append(Subscription(channel=event_type))
        await self.save()

    async def remove_subscription(self, event_type: str):
        try:
            sub = next(
                sub for sub in self.event_subscriptions if sub.event_type == event_type
            )
        except StopIteration:
            return
        self.event_subscriptions.remove(sub)
        await self.save()

    @classmethod
    async def create_application(cls, name: str):
        app = cls(name=name, tags=["my-tag"])
        await app.save()
        return app

    @classmethod
    def find_subscribed(cls, to: str):
        return cls.find({f"{cls.event_subscriptions}.{Subscription.event_type}": to})

    @classmethod
    async def find_subscribed_id(cls, to: str) -> List[PydanticObjectId]:
        return list(
            map(
                lambda v: v.id,
                await cls.find_subscribed(to).project(IdProjection).to_list(),
            )
        )

    @classmethod
    def find_by_key(cls, key: str):
        return cls.find_one({"access_key": key})

    class Collection:
        name = "applications"


class ApplicationView(BaseModel):
    id: PydanticObjectId = Field(alias="_id")
    tags: List[str]
    disabled: bool
    name: str
    description: Optional[str]


class SentEventTrace(Document):
    from_app: Optional[PydanticObjectId]
    to_app: PydanticObjectId
    event_type: str
    last_event: datetime = Field(default_factory=datetime.now)
    times_used: int = 1

    class Collection:
        name = "event_traces"

    @classmethod
    def add_trace(
        cls,
        event_type: str,
        to_app: Union[PydanticObjectId, Iterable[PydanticObjectId]],
        from_app: Optional[PydanticObjectId],
    ):
        if isinstance(to_app, PydanticObjectId):
            return cls._add_trace(event_type, to_app, from_app)
        else:
            return asyncio.gather(
                *(cls._add_trace(event_type, app_id, from_app) for app_id in to_app)
            )

    @classmethod
    async def _add_trace(
        cls,
        event_type: str,
        to_app: PydanticObjectId,
        from_app: Optional[PydanticObjectId],
    ):
        await cls.find(
            cls.to_app == to_app,
            cls.event_type == event_type,
            cls.from_app == from_app,
        ).upsert(
            SetOp({cls.last_event: datetime.now()}),
            Inc(cls.count),
            on_insert=cls(event_type=event_type, from_app=from_app, to_app=to_app),
        )
