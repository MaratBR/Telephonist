from datetime import datetime, timezone
from typing import TypeVar, Union
from uuid import UUID

from beanie import PydanticObjectId
from pydantic import Field, constr

__all__ = ("IdProjection", "Identifier", "convert_to_utc")

from server.common.models.base_model import AppBaseModel


class IdProjection(AppBaseModel):
    id: Union[PydanticObjectId, UUID, str, int] = Field(alias="_id")


Identifier = constr(regex=r"^[\d\w%^$#&\-]+\Z")
_DT = TypeVar("_DT", bound=datetime)


def convert_to_utc(dt: datetime):
    if dt.tzinfo is not None:
        if dt.utcoffset().total_seconds() != 0:
            dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
