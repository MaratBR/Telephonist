from typing import Any, Optional, Type, TypeVar

from beanie import Document, PydanticObjectId
from fastapi import HTTPException
from starlette import status

from server.models.common import SoftDeletes

T = TypeVar("T")


class Errors:
    @staticmethod
    def raise404_if_none(value: Optional[T], message: str = "Not found") -> T:
        if value is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, message)
        return value

    @staticmethod
    def raise404_if_false(value: bool, message: str = "Not found"):
        if not value:
            raise HTTPException(status.HTTP_404_NOT_FOUND, message)


class Prefixer:
    _prefix: str

    def __init__(self, prefix: Optional[str] = None):
        if prefix is None:
            self._prefix = "/"
        else:
            self._prefix = "/" + prefix + "/"

    def __call__(self, *parts: Any):
        return self._prefix + "/".join(map(str, parts))


class MonitoringEvents(Prefixer):
    def app(self, app_id: PydanticObjectId):
        return self("app", app_id)

    def app_events(self, app_id: PydanticObjectId):
        return self("appEvents", app_id)

    def sequence(self, sequence_id: PydanticObjectId):
        return self("sequence", sequence_id)

    def sequence_events(self, sequence_id: PydanticObjectId):
        return self("sequenceEvents", sequence_id)

    def sequence_logs(self, sequence_id: PydanticObjectId):
        return self("sequenceLogs", sequence_id)

    def app_logs(self, app_id: PydanticObjectId):
        return self("appLogs", app_id)


class AuthEvents(Prefixer):
    def user(self, user_id: PydanticObjectId):
        return self("user", user_id)


class ChannelGroups(Prefixer):
    def __init__(self):
        super(ChannelGroups, self).__init__()
        self.monitoring = MonitoringEvents("monitoring")
        self.auth = AuthEvents("auth")

    def app(self, app_id: PydanticObjectId):
        return self("app", app_id)

    def event(self, event_key: str):
        return self("events", "key", event_key)


CG = ChannelGroups()


async def require_model_with_id(
    model: Type[Document], document_id, *, message: str = "Not found"
):
    if issubclass(model, SoftDeletes):
        q = model.not_deleted()
    else:
        q = model
    Errors.raise404_if_false(
        await q.find({"_id": document_id}).exists(), message=message
    )
