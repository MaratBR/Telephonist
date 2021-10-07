import enum
from datetime import datetime
from typing import Union, Optional, Any, List, Awaitable

import nanoid
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from starlette.websockets import WebSocket

from server.auth.models import User, TokenSubjectMixin
from server.auth.tokens import static_token_factory
from server.database import register_model


class StatusType(str, enum.Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    FAILED = 'failed'
    FINISHING = 'finishing'
    INITIALIZATION = 'initialization'
    COMPLETED = 'completed'


class StatusEntry(BaseModel):
    title: Optional[str]
    subtitle: Optional[str]
    type: StatusType
    progress: Optional[int]
    started_at: Optional[datetime]
    uid: str = Field(default_factory=nanoid.generate)


class StatusHistory(Document):
    # TODO
    pass


class ApplicationSettings(BaseModel):
    receive_offline: bool = False


class Subscription(BaseModel):
    channel: str
    subscribed_at: datetime = Field(default_factory=datetime.utcnow)


class ConnectionInfo(BaseModel):
    id: str = Field(default_factory=nanoid.generate)
    ip: Optional[str]
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    disconnected_at: Optional[datetime] = None

    @classmethod
    def from_websocket(cls, ws: WebSocket):
        return cls(ip=ws.client.host)


@register_model
class Application(Document, TokenSubjectMixin):
    name: Indexed(str, unique=True)
    display_name: Optional[str] = None
    access_token: Indexed(str, unique=True) = Field(default_factory=static_token_factory(prefix='app'))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    disabled: bool = False
    statuses: List[StatusEntry] = Field(default_factory=list)
    settings: ApplicationSettings = Field(default_factory=ApplicationSettings)
    tags: List[str] = Field(default_factory=list)
    connection_info: List[ConnectionInfo] = Field(default_factory=list)

    event_subscriptions: List[Subscription] = Field(default_factory=list)
    event_raised: List[str] = Field(default_factory=list)

    @property
    def has_connection(self):
        return len(self.connection_info) > 0

    async def add_subscription(self, event_type: str):
        if any(sub.channel == event_type for sub in self.event_subscriptions):
            return
        self.event_subscriptions.append(Subscription(channel=event_type))
        await self.save()

    async def remove_subscription(self, event_type: str):
        try:
            sub = next(sub for sub in self.event_subscriptions if sub.channel == event_type)
        except StopIteration:
            return
        self.event_subscriptions.remove(sub)
        await self.save()

    @classmethod
    async def create_application(cls, name: str):
        app = cls(name=name, tags=['my-tag'])
        await app.save()
        return app

    @classmethod
    async def populate(cls):
        APPLICATION_NAMES = [
            'text',
            'test',
            'MyApp',
            'TestApp',
            'SuomiNPPProcessor',
            'ArcticaM-Software'
        ]

        for i in range(10):
            for app_name in APPLICATION_NAMES:
                try:
                    await cls.create_application(app_name + str(i))
                except DuplicateKeyError:
                    pass


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
    published_at: datetime = Field(default_factory=datetime.utcnow)
    publisher_ip: str = '127.0.0.1'

    @classmethod
    def create_event(
            cls,
            event_type: str,
            source: Union[User, Application],
            data: Optional[Union[dict, list]] = None,
            ip: Optional[str] = None
    ) -> Awaitable['Event']:
        event = cls(
            publisher_ip=ip,
            event_type=event_type,
            data=data,
            source_type=EventSource.USER if isinstance(source, User) else EventSource.APPLICATION,
            source_id=source.id
        )
        return event.save()


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


@register_model
class Server(Document):
    name: Optional[str]
    ip: Indexed(str, unique=True)
    online: Optional[bool] = None


@register_model
class EventQueueBucket(Document):
    events: List[Event]
    app_id: Indexed(PydanticObjectId)
