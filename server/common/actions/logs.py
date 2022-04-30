from typing import Any, List, Optional

from beanie import PydanticObjectId

from server.common.channels import get_channel_layer
from server.common.models import AppBaseModel
from server.database import AppLog, Severity


class LogRecord(AppBaseModel):
    t: int
    severity: Severity
    body: str
    extra: Optional[dict[str, Any]]


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
            t=log.t,
            severity=log.severity,
            sequence_id=sequence_id,
        )
        for log in logs
    ]
    result = await AppLog.insert_many(models)
    print(f"inserted {len(result.inserted_ids)} logs out of {len(models)}")
    for i in range(len(models)):
        models[i].id = PydanticObjectId(result.inserted_ids[i])
    groups = (
        [f"m/sequenceLogs/{sequence_id}", f"m/appLogs/{app_id}"]
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