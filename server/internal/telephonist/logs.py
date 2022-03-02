from datetime import datetime
from typing import Any, List, Optional

from beanie import PydanticObjectId
from pydantic import validator

from server.internal.channels import get_channel_layer
from server.internal.telephonist import CG
from server.models.common import AppBaseModel, convert_to_utc
from server.models.telephonist import AppLog, Severity


class LogRecord(AppBaseModel):
    t: datetime
    severity: Severity
    body: Any

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
            CG.monitoring.sequence_logs(sequence_id),
            CG.monitoring.app_logs(app_id),
        ]
        if sequence_id
        else [CG.monitoring.app_logs(app_id)]
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