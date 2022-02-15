from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import Field, constr

__all__ = ("IdProjection", "Identifier", "convert_to_utc")

from server.models.common import AppBaseModel


class IdProjection(AppBaseModel):
    id: Any = Field(alias="_id")


Identifier = constr(regex=r"^[\d\w%^$#&\-]+$")
_DT = TypeVar("_DT", bound=datetime)


def convert_to_utc(dt: datetime):
    if dt.tzinfo is not None:
        if dt.utcoffset().total_seconds() != 0:
            dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
