from typing import Optional

from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from beanie.operators import In
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from server.database import AppLog, Severity

logs_router = APIRouter(prefix="/logs")


@logs_router.get("", response_class=ORJSONResponse)
async def get_logs(
    app_id: Optional[PydanticObjectId] = None,
    sequence_id: Optional[PydanticObjectId] = None,
    debug: bool = False,
    info: bool = True,
    warn: bool = True,
    err: bool = True,
    fatal: bool = True,
    cur: Optional[PydanticObjectId] = None,
):
    if debug and info and warn and err and fatal:
        find = []
    else:
        allowed_levels = []
        if debug:
            allowed_levels.append(Severity.DEBUG)
        if info:
            allowed_levels.append(Severity.INFO)
        if warn:
            allowed_levels.append(Severity.WARNING)
        if err:
            allowed_levels.append(Severity.ERROR)
        if fatal:
            allowed_levels.append(Severity.FATAL)
        find = [In(AppLog.severity, allowed_levels)]
    if app_id:
        find.append(AppLog.app_id == app_id)
    if sequence_id:
        find.append(AppLog.sequence_id == sequence_id)
    if cur:
        find.append(AppLog.id > cur)

    logs = (
        await AppLog.find(*find)
        .limit(1000)
        .sort(("_id", SortDirection.DESCENDING))
        .to_list()
    )

    return [
        {
            "t": log.created_at,
            "body": log.body,
            "severity": log.severity,
            "app_id": str(log.app_id),
            "sequence_id": str(log.sequence_id),
            "_id": str(log.id),
        }
        for log in logs
    ]
