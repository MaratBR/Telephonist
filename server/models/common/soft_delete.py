from datetime import datetime
from typing import Any, ClassVar, Optional, Type, TypeVar, Union

from beanie.odm.queries.find import FindOne
from beanie.operators import NE, Eq
from pydantic import Field

from .base_model import BaseDocument

__all__ = ("SoftDeletes",)

DocType = TypeVar("DocType", bound=Union["SoftDeletes", BaseDocument])


class SoftDeletes(BaseDocument):
    deleted_at: Optional[datetime] = Field()
    NOT_DELETED_COND: ClassVar[Eq] = Eq("deleted_at", None)
    DELETED_COND: ClassVar[Eq] = NE("deleted_at", None)

    @classmethod
    def _not_deleted_condition(cls):
        return cls.deleted_at == None  # noqa

    async def soft_delete(self: DocType):
        await self.update({"$set": {"deleted_at": datetime.utcnow()}})

    @classmethod
    def not_deleted(cls: Type[DocType]):
        return cls.find(cls.NOT_DELETED_COND)

    @classmethod
    def deleted(cls: Type[DocType]):
        return cls.find(cls.DELETED_COND)

    @classmethod
    def get_not_deleted(cls: Type[DocType], _id: Any) -> FindOne[DocType]:
        return cls.find_one(Eq(cls.deleted_at, None), {"_id": _id})
