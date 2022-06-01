from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import Depends

from server.common.channels.layer import ChannelLayer, get_channel_layer
from server.common.models import AppBaseModel
from server.database import AppLog, Severity


class LogRecord(AppBaseModel):
    t: int
    severity: Severity
    body: str
    extra: Optional[dict[str, Any]]


class LogsService:
    def __init__(
        self, channel_layer: ChannelLayer = Depends(get_channel_layer)
    ):
        self._channel_layer = channel_layer

    async def send_logs(
        self,
        app_id: PydanticObjectId,
        sequence_id: Optional[PydanticObjectId],
        logs: list[LogRecord],
    ):
        if len(logs) == 0:
            return
        models = [
            AppLog(
                body=log.body,
                app_id=app_id,
                t=log.t,
                severity=log.severity,
                sequence_id=sequence_id,
            )
            for log in logs
        ]
        result = await AppLog.insert_many(models)
        for i in range(len(models)):
            models[i].id = PydanticObjectId(result.inserted_ids[i])
        groups = (
            [f"m/sequenceLogs/{sequence_id}", f"m/appLogs/{app_id}"]
            if sequence_id
            else [f"m/appLogs/{app_id}"]
        )
        await self._channel_layer.groups_send(
            groups,
            "logs",
            {
                "app_id": app_id,
                "sequence_id": sequence_id,
                "count": len(models),
                "cursor": PydanticObjectId(result.inserted_ids[0]),
            },
        )
        return models
