from datetime import datetime
from typing import Optional

from beanie import Document, PydanticObjectId, Indexed
from pydantic import Field, BaseModel

from server.auth.tokens import static_token_factory
from server.database import register_model


@register_model
class ApplicationHostToken(Document):
    token: Indexed(str, unique=True) = Field(default_factory=static_token_factory(prefix='appHost'))
    revoked: bool = False
    revoked_at: Optional[datetime] = None

    async def revoke(self):
        self.revoked = True
        self.revoked_at = datetime.utcnow()
        await self.save_changes()

    @classmethod
    async def new(cls):
        t = cls()
        await t.save()
        return t


class HostSoftware(BaseModel):
    version: Optional[str]
    name: str


@register_model
class ApplicationHost(Document):
    name: str
    software: Optional[HostSoftware] = None
    last_active: Optional[datetime] = None
    server_id: PydanticObjectId
    server_ip: str
    is_online: bool
    pid: Optional[int]


