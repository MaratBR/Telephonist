from datetime import datetime
from typing import Optional, Type, TypeVar, Union

from beanie import Document, PydanticObjectId
from beanie.odm.queries.find import FindOne
from beanie.operators import Eq
from pydantic import Field

DocType = TypeVar("DocType", bound=Union["SoftDeletes", Document])


class SoftDeletes(Document):
    deleted_at: Optional[datetime] = Field()

    @classmethod
    def _not_deleted_condition(cls):
        return cls.deleted_at == None  # noqa

    async def soft_delete(self: DocType):
        await self.update({"deleted_at": datetime.utcnow()})

    @classmethod
    def not_deleted(cls: Type[DocType]):
        return cls.find(Eq(cls.deleted_at, None))

    @classmethod
    def get_not_deleted(cls: Type[DocType], _id: PydanticObjectId) -> FindOne[DocType]:
        return cls.find_one(Eq(cls.deleted_at, None), {"_id": _id})
