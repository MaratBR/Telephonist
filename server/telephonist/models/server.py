from datetime import datetime
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field

from server.database import register_model


@register_model
class Server(Document):
    name: Optional[str] = None
    ip: Indexed(str, unique=True) = None
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    os: Optional[str] = None

    @classmethod
    async def report_server(cls, ip: str):
        if not await cls.find_one(cls.ip == ip).exists():
            await cls(ip=ip).save()
