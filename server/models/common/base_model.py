from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel as _BaseModel

__all__ = ("BaseDocument", "AppBaseModel")


def stringify_datetime(dt: datetime):
    if dt.tzinfo is timezone.utc:
        return dt.isoformat()
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class AppBaseModel(_BaseModel):
    class Config:
        json_encoders = {datetime: stringify_datetime}


class BaseDocument(Document):
    class Config:
        json_encoders = {datetime: stringify_datetime}
