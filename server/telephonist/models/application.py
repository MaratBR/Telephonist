import enum
from datetime import datetime
from typing import Optional, List

import nanoid
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from starlette.websockets import WebSocket

from server.auth.models import TokenSubjectMixin
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
    client_name: Optional[str] = None

    @classmethod
    def from_websocket(cls, ws: WebSocket):
        return cls(ip=ws.client.host)


@register_model
class Application(Document, TokenSubjectMixin):
    name: Indexed(str, unique=True)
    description: Optional[str] = None
    token: Indexed(str, unique=True) = Field(default_factory=static_token_factory(prefix='app'))
    disabled: bool = False
    statuses: List[StatusEntry] = Field(default_factory=list)
    settings: ApplicationSettings = Field(default_factory=ApplicationSettings)
    tags: List[str] = Field(default_factory=list)
    connection_info: List[ConnectionInfo] = Field(default_factory=list)
    event_subscriptions: List[Subscription] = Field(default_factory=list)

    class PublicView(BaseModel):
        id: PydanticObjectId = Field(alias='_id')
        tags: List[str]
        disabled: bool
        name: str
        description: Optional[str]
        settings: ApplicationSettings
        connection_info: List[ConnectionInfo]
        event_subscriptions: List[Subscription]

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