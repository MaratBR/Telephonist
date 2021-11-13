import random
from datetime import datetime, timedelta
from typing import Awaitable

import pymongo
from beanie import Document
from pydantic import Field

from server.database import register_model

_rand = random.SystemRandom()


def generate_security_code(length: int = 8):
    return str(_rand.randint(10**length - 1, 0)).zfill(length)


@register_model
class AppHostSecurityCode(Document):
    code: str = Field(default_factory=generate_security_code)
    expires_at: datetime
    confirmed: bool = False

    @classmethod
    async def new(cls, lifetime: timedelta = timedelta(minutes=10)) -> str:
        code = cls(expires_at=datetime.utcnow() + lifetime)
        await code.save()
        return code.code

    @classmethod
    def exists(cls, code: str):
        return cls.find({'_id': code}).exists()

    @classmethod
    def get_valid_code(cls, code: str) -> Awaitable['AppHostSecurityCode']:
        return cls.find_one({'code': code}, cls.expires_at > datetime.utcnow())

    @classmethod
    def delete_code(cls, code: str):
        return cls.find({'code': code}).delete()

    class Collection:
        name = 'apphost_security_codes'
        indexes = [
            pymongo.IndexModel('expires_at', name='expires_at_ttl', expireAfterSeconds=60)
        ]
