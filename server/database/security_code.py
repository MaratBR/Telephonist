import random
from datetime import datetime, timedelta
from typing import ClassVar, Optional

import pymongo
from pydantic import Field

from server.common.models import BaseDocument
from server.database.registry import register_model

_rand = random.SystemRandom()


def generate_security_code(length: int = 8):
    return str(_rand.randint(0, 10**length - 1)).zfill(length)


@register_model
class OneTimeSecurityCode(BaseDocument):
    DEFAULT_LIFETIME: ClassVar[timedelta] = timedelta(minutes=10)

    id: str = Field(default_factory=generate_security_code)
    expires_at: datetime
    code_type: str
    confirmed: bool = False
    ip_address: str

    @classmethod
    async def new(
        cls,
        code_type: str,
        ip_address: str,
        lifetime: timedelta = DEFAULT_LIFETIME,
    ) -> "OneTimeSecurityCode":
        code = await cls._generate_code()
        code_inst = cls(
            id=code,
            expires_at=datetime.utcnow() + lifetime,
            code_type=code_type,
            ip_address=ip_address,
        )
        await code_inst.save()
        return code_inst

    @classmethod
    async def _generate_code(cls) -> str:
        length = 8
        attempts = 0
        while True:
            code = generate_security_code(length)
            if not await cls.find({"_id": code}).exists():
                break
            attempts += 1
            if attempts % 5 == 0:
                length += 1
        return code

    @classmethod
    def exists(cls, code: str, type_: Optional[str] = None):
        find = {
            "_id": code,
        }
        if type_:
            find["code_type"] = type_
        return cls.find(find).exists()

    @classmethod
    async def get_valid_code(
        cls, code_type: str, code: str
    ) -> Optional["OneTimeSecurityCode"]:
        return await cls.find_one(
            {"_id": code, "code_type": code_type},
            cls.expires_at > datetime.utcnow(),
        )

    @classmethod
    def delete_code(cls, code: str):
        return cls.find({"code": code}).delete()

    class Collection:
        name = "onetime_security_codes"
        indexes = [
            pymongo.IndexModel(
                "expires_at", name="expires_at_ttl", expireAfterSeconds=60
            )
        ]
