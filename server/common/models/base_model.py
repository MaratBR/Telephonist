from datetime import datetime, timezone

import orjson
from beanie import Document
from pydantic import BaseModel as _BaseModel

__all__ = ("BaseDocument", "AppBaseModel")


def stringify_datetime(dt: datetime):
    if dt.tzinfo is timezone.utc:
        return dt.isoformat()
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def orjson_dumps(v, *, default):
    # orjson.dumps returns bytes, to match standard json.dumps we need to decode
    return orjson.dumps(v, default=default).decode()


class AppBaseModel(_BaseModel):
    class Config:
        json_encoders = {datetime: stringify_datetime}


class BaseDocument(Document):
    class Config:
        json_encoders = {datetime: stringify_datetime}
