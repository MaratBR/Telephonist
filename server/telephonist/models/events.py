import enum
from datetime import datetime
from typing import Optional, Any, Union, List

from beanie import Document, PydanticObjectId, Indexed
from pydantic import Field, BaseModel

from server.auth.models import User
from server.database import register_model
from .application import Application
from ...common.models import IdProjection


class EventSource(str, enum.Enum):
    USER = 'user'
    APPLICATION = 'app'
    UNKNOWN = '?'


@register_model
class EventData(Document):
    id: str
    description: Optional[str] = None


@register_model
class Event(Document):
    source_type: EventSource = EventSource.UNKNOWN
    source_id: Optional[PydanticObjectId]
    event_type: Indexed(str)
    data: Optional[Any] = None
    publisher_ip: str = '127.0.0.1'
    receivers: List[PydanticObjectId] = Field(default_factory=list)

    class Collection:
        name = 'events'
        indexes = ['receivers']

    @classmethod
    def by_type(cls, event_type: str):
        return cls.find(cls.event_type == event_type.lower())

    @classmethod
    async def create_event(
            cls,
            event_type: str,
            source: Union[User, Application],
            data: Optional[Union[dict, list]] = None,
            ip: Optional[str] = None
    ) -> 'Event':
        receivers = await Application\
            .find({'event_subscriptions.channel': event_type})\
            .project(IdProjection).to_list()
        receivers = [p.id for p in receivers]
        event = cls(
            publisher_ip=ip,
            event_type=event_type.lower(),
            data=data,
            source_type=EventSource.USER if isinstance(source, User) else EventSource.APPLICATION,
            source_id=source.id
        )
        return await event.save()


class EventMessage(BaseModel):
    id: PydanticObjectId
    name: str
    published_at: datetime
    publisher_ip: str
    data: Optional[Any]
    source_type: EventSource
    source_id: PydanticObjectId

    @classmethod
    def from_event(cls, event: Event):
        return cls(
            name=event.event_type, id=event.id, publisher_ip=event.publisher_ip,
            data=event.data, published_at=event.published_at, source_type=event.source_type,
            source_id=event.source_id
        )



