import random
from datetime import datetime, timedelta
from typing import Awaitable

import pymongo
from beanie import Document
from pydantic import Field

from server.database import register_model

_rand = random.SystemRandom()


def generate_security_code(length: int = 8):
    return str(_rand.randint(0, 10**length - 1)).zfill(length)


@register_model
class OneTimeSecurityCode(Document):
    id: str = Field(default_factory=generate_security_code, alias='_id')
    expires_at: datetime
    code_type: str
    confirmed: bool = False
    created_by: str
    ip_address: str

    @classmethod
    async def new(cls,
                  code_type: str,
                  created_by: str,
                  ip_address: str,
                  lifetime: timedelta = timedelta(minutes=10)) -> 'OneTimeSecurityCode':
        code = await cls._generate_code()
        code_inst = cls(id=code, expires_at=datetime.now() + lifetime, code_type=code_type,
                        ip_address=ip_address, created_by=created_by)
        await code_inst.save()
        return code_inst

    @classmethod
    async def _generate_code(cls) -> str:
        length = 8
        attempts = 0
        while True:
            code = generate_security_code(length)
            if not await cls.find({'_id': code}).exists():
                break
            attempts += 1
            if attempts % 5 == 0:
                length += 1
        return code

    @classmethod
    def exists(cls, code_type: str, code: str):
        return cls.find({'_id': code, }).exists()

    @classmethod
    def get_valid_code(cls, code_type: str, code: str) -> Awaitable['OneTimeSecurityCode']:
        return cls.find_one({'_id': code, 'code_type': code_type}, cls.expires_at > datetime.now())

    @classmethod
    def delete_code(cls, code: str):
        return cls.find({'code': code}).delete()

    class Collection:
        name = 'onetime_security_codes'
        indexes = [
            pymongo.IndexModel('expires_at', name='expires_at_ttl', expireAfterSeconds=60)
        ]
