import enum
from typing import Optional, Any

from beanie import Document, PydanticObjectId

from server.database import register_model


class AppLogType(enum.Enum):
    STDOUT = 'stdout'
    STDERR = 'stderr'
    CUSTOM = 'custom'
    EXCEPTION = 'exception'


class Severity(enum.IntEnum):
    NONE = 0
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    FATAL = 50


AppLogBody = str


@register_model
class AppLog(Document):
    app_id: PydanticObjectId
    type: AppLogType
    severity: Severity
    body: AppLogBody
    meta: Optional[Any] = None

    class Collection:
        name = 'app_logs'

    @classmethod
    async def _log(cls, body: AppLogBody, app_id: PydanticObjectId, log_type: AppLogType, severity: Severity, meta: Optional[Any]):
        await cls(app_id=app_id, type=log_type, severity=severity, meta=meta, body=body).save()

    @classmethod
    def stdout(cls, body: str, app_id: PydanticObjectId, severity: Severity = Severity.INFO, meta: Optional[Any] = None):
        return cls._log(body, app_id, AppLogType.STDOUT, severity, meta)
