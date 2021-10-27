import enum

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
    body: str

    class Collection:
        name = 'app_logs'

    @classmethod
    async def _log(cls, app_id: PydanticObjectId, log_type: AppLogType, severity: Severity):
        pass
