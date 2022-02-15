import enum
from datetime import datetime
from typing import Any, Optional

from beanie import PydanticObjectId
from beanie.odm.queries.find import FindMany
from pydantic import Field

from server.database import register_model
from server.models.common import BaseDocument
from server.settings import settings


class Severity(enum.IntEnum):
    UNKNOWN = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    FATAL = 50


@register_model
class AppLog(BaseDocument):
    app_id: PydanticObjectId
    severity: Severity = Severity.UNKNOWN
    body: Any
    task_name: Optional[str]
    sequence_id: Optional[PydanticObjectId]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @staticmethod
    def __motor_create_collection_params__():
        if settings.use_capped_collection_for_logs:
            return {
                "capped": True,
                "size": settings.logs_capped_collection_max_size_mb * 2**20,
            }

    @classmethod
    async def _log(
        cls,
        body: Any,
        app_id: PydanticObjectId,
        severity: Severity,
        meta: Optional[Any],
    ):
        await cls(
            app_id=app_id,
            severity=severity,
            meta=meta,
            body=body,
        ).insert()

    @classmethod
    def find_before(cls, before: datetime) -> FindMany["AppLog"]:
        oid = hex(int(before.timestamp()))[2:] + "0000000000000000"
        return cls.find({"_id": {"$lt": oid}})

    class Collection:
        name = "app_logs"
