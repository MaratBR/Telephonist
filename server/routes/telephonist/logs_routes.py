from datetime import datetime
from typing import Any, Optional

from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import Field

from server.internal.auth.dependencies import AccessToken
from server.internal.channels import WSTicket, WSTicketModel
from server.internal.channels.hub import Hub, bind_message, ws_controller
from server.models.common import AppBaseModel
from server.models.telephonist import (
    Application,
    AppLog,
    EventSequence,
    Severity,
)
from server.routes.telephonist.utils import get_application_from_key
from server.utils.common import QueryDict

logs_router = APIRouter(prefix="/logs", tags=["logs"])


class LogBody(AppBaseModel):
    body: Any
    sequence_id: Optional[PydanticObjectId]
    severity: Severity = Severity.UNKNOWN
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GetLogs(AppBaseModel):
    before: Optional[datetime]
    after: Optional[datetime]


@logs_router.get("/{app_id}", dependencies=[AccessToken()])
async def get_logs(app_id: PydanticObjectId, params=QueryDict(GetLogs)):
    filter_conditions = []
    if params.after:
        filter_conditions.append(AppLog.created_at > params.after)
    if params.before:
        filter_conditions.append(AppLog.created_at < params.before)
    logs = (
        await AppLog.find(AppLog.app_id == app_id, *filter_conditions)
        .sort(("created_at", SortDirection.DESCENDING))
        .limit(500)
        .to_list()
    )
    return logs


@logs_router.get("/{app_id}/export")
async def export_logs(app_id: PydanticObjectId):
    return "NO"


@logs_router.post("/add")
async def create_log_entry(
    body: LogBody = Body(...),
    app: Application = Depends(get_application_from_key),
):
    if body.sequence_id:
        seq = await EventSequence.get(body.sequence_id)
        if seq is None:
            raise HTTPException(
                404, f"sequence with id {body.sequence_id} does not exist"
            )
        if seq.app_id != app.id:
            raise HTTPException(
                401,
                f"this application ({app.id}) has no access to sequence"
                f" {seq.id}",
            )
        task_name = seq.task_name
    else:
        task_name = None
    log = AppLog(
        sequence_id=body.sequence_id,
        task_name=task_name,
        body=body.body,
        severity=body.severity,
        app_id=app.id,
    )
    await log.insert()
    return {"detail": "Log accepted"}


LogMessage = LogBody


@ws_controller(logs_router, "/ws")
class LogsHub(Hub):
    _cache: dict
    ticket: WSTicketModel[Application] = WSTicket(Application)

    def on_connected(self):
        self._cache = {}

    @bind_message("log")
    async def log(self, message: LogMessage):
        task_name = self._cache.get(f"{message.sequence_id}_task_name")
        if task_name is None:
            seq = await EventSequence.get(message.sequence_id)
            if seq is None or seq.app_id != self.ticket.sub:
                return
            task_name = seq.task_name
            self._cache[f"{message.sequence_id}_task_name"] = task_name

        log = AppLog(
            sequence_id=message.sequence_id,
            task_name=task_name,
            body=message.body,
            app_id=message,
        )
        await log.insert()
