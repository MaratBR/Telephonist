import enum
import time
from datetime import datetime
from typing import Any, Optional

from beanie import PydanticObjectId
from beanie.odm.queries.find import FindMany
from pydantic import Field

from server.common.models import BaseDocument
from server.database.registry import register_model
from server.settings import Settings


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
    body: str
    extra: Optional[dict[str, Any]]
    sequence_id: Optional[PydanticObjectId]
    t: int = Field(default_factory=lambda: time.time_ns() // 1000)

    @staticmethod
    def __motor_create_collection_params__(settings: Settings):
        if settings.use_capped_collection_for_logs:
            return {
                "capped": True,
                "size": settings.logs_capped_collection_max_size_mb * 2**20,
            }

    @classmethod
    def find_before(cls, before: datetime) -> FindMany["AppLog"]:
        oid = hex(int(before.timestamp()))[2:] + "0000000000000000"
        return cls.find({"_id": {"$lt": oid}})

    class Collection:
        name = "app_logs"
