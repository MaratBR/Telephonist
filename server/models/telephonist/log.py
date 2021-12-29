import enum
from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from beanie.odm.queries.find import FindMany

from server.database import register_model


class AppLogType(enum.Enum):
    STDOUT = "stdout"
    STDERR = "stderr"
    CUSTOM = "custom"
    EXCEPTION = "exception"


class Severity(enum.IntEnum):
    NONE = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    FATAL = 50


@register_model
class AppLog(Document):
    app_id: PydanticObjectId
    type: AppLogType
    severity: Severity
    body: Any
    meta: Optional[Any] = None

    class Collection:
        name = "app_logs"

    @classmethod
    async def _log(
        cls,
        body: Any,
        app_id: PydanticObjectId,
        log_type: AppLogType,
        severity: Severity,
        meta: Optional[Any],
    ):
        await cls(
            app_id=app_id, type=log_type, severity=severity, meta=meta, body=body
        ).save()

    @classmethod
    def stdout(
        cls,
        body: str,
        app_id: PydanticObjectId,
        severity: Severity = Severity.INFO,
        meta: Optional[Any] = None,
    ):
        return cls._log(body, app_id, AppLogType.STDOUT, severity, meta)

    @classmethod
    def find_before(cls, before: datetime) -> FindMany["AppLog"]:
        oid = hex(int(before.timestamp()))[2:] + "0000000000000000"
        return cls.find({"_id": {"$lt": oid}})
