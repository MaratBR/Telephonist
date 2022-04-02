from datetime import datetime
from typing import Any, List, Optional

from beanie import PydanticObjectId
from pydantic import validator

from server.common.channels import get_channel_layer
from server.common.internal.utils import CG
from server.common.models import AppBaseModel, convert_to_utc
from server.database import AppLog, Severity


class LogRecord(AppBaseModel):
    t: datetime
    severity: Severity
    body: str
    extra: Optional[dict[str, Any]]

    _t_validator = validator("t", allow_reuse=True)(convert_to_utc)


async def send_logs(
    app_id: PydanticObjectId,
    sequence_id: Optional[PydanticObjectId],
    logs: List[LogRecord],
):
    if len(logs) == 0:
        return
    models = [
        AppLog(
            body=log.body,
            app_id=app_id,
            created_at=log.t,
            severity=log.severity,
            sequence_id=sequence_id,
        )
        for log in logs
    ]
    result = await AppLog.insert_many(models)
    for i in range(len(models)):
        models[i].id = PydanticObjectId(result.inserted_ids[i])
    groups = (
        [
            f"m/sequenceLogs/{sequence_id}",
            f"m/appLogs/{app_id}"
        ]
        if sequence_id
        else [f"m/appLogs/{app_id}"]
    )
    await get_channel_layer().groups_send(
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
