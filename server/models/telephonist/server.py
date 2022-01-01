from datetime import datetime
from typing import Optional, Union

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from starlette.datastructures import Address

from server.database import register_model


@register_model
class Server(Document):
    name: Optional[str] = None
    ip: Indexed(str, unique=True) = None
    last_seen: datetime = Field(default_factory=datetime.now)
    os: Optional[str] = None

    class ServerView(BaseModel):
        id: PydanticObjectId = Field(alias="_id")
        last_seen: datetime
        ip: str
        os: Optional[str]

    class Collection:
        name = "servers"

    @classmethod
    async def report_server(cls, ip: Union[str, Address], os: Optional[str] = None):
        if isinstance(ip, Address):
            ip = ip.host
        ip = ip.lower()
        server = await cls.find_one(cls.ip == ip)
        if server is None:
            await cls(ip=ip, os=os).save()
        else:
            server.last_seen = datetime.utcnow()
            server.os = os
            await server.replace()
