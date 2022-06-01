import asyncio
from datetime import datetime
from typing import ClassVar, Iterable, List, Optional, Union

import pymongo
from beanie import Indexed, PydanticObjectId
from beanie.operators import Inc
from beanie.operators import Set as SetOp
from pydantic import Field

from server.auth.utils import static_key_factory
from server.common.models import (
    AppBaseModel,
    BaseDocument,
    IdProjection,
    SoftDeletes,
)
from server.database.registry import register_model


@register_model
class Application(SoftDeletes):
    ARBITRARY_TYPE: ClassVar[str] = "arbitrary"
    AGENT_TYPE: ClassVar[str] = "agent"

    display_name: str
    name: Indexed(str, unique=True)
    description: str = ""
    disabled: bool = False
    tags: List[str] = Field(default_factory=list)
    access_key: str = Field(default_factory=static_key_factory())

    @property
    def has_connection(self):
        return len(self.connection_info) > 0

    async def add_subscription(self, event_type: str):
        if any(
            sub.event_type == event_type for sub in self.event_subscriptions
        ):
            return
        self.event_subscriptions.append(event_type)
        await self.save()

    async def remove_subscription(self, event_type: str):
        try:
            sub = next(
                sub
                for sub in self.event_subscriptions
                if sub.event_type == event_type
            )
        except StopIteration:
            return
        self.event_subscriptions.remove(sub)
        await self.save()

    @classmethod
    def find_subscribed(cls, to: str):
        return cls.find({"event_subscriptions": to})

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
        return cls.find_one({"access_key": key}, cls.NOT_DELETED_COND)

    class Collection:
        name = "applications"
        indexes = [
            [
                ("name", pymongo.TEXT),
                ("display_name", pymongo.TEXT),
                ("tags", pymongo.TEXT),
                ("description", pymongo.TEXT),
            ]
        ]

    class Settings:
        use_state_management = True


class ApplicationView(AppBaseModel):
    id: PydanticObjectId = Field(alias="_id")
    tags: List[str]
    disabled: bool
    name: str
    description: Optional[str]
    access_key: str
    display_name: str


class SentEventTrace(BaseDocument):
    from_app: Optional[PydanticObjectId]
    to_app: PydanticObjectId
    event_type: str
    last_event: datetime = Field(default_factory=datetime.utcnow)
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
                *(
                    cls._add_trace(event_type, app_id, from_app)
                    for app_id in to_app
                )
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
            SetOp({cls.last_event: datetime.utcnow()}),
            Inc(cls.count),
            on_insert=cls(
                event_type=event_type, from_app=from_app, to_app=to_app
            ),
        )
