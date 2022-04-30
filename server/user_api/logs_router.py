from typing import Optional

from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from beanie.operators import In
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from server.database import Application, AppLog, EventSequence, Severity

logs_router = APIRouter(prefix="/logs")


@logs_router.get("", response_class=ORJSONResponse)
async def get_logs(
    app_id: Optional[PydanticObjectId] = None,
    sequence_id: Optional[PydanticObjectId] = None,
    debug: bool = True,
    info: bool = True,
    warn: bool = True,
    err: bool = True,
    fatal: bool = True,
    cur: Optional[int] = None,
    limit: int = 200,
):
    limit = max(20, min(limit, 1000))
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
    if sequence_id:
        find.append(AppLog.sequence_id == sequence_id)
        sequence = await EventSequence.get(sequence_id)
        app = await Application.get(sequence.app_id)

        app = {
            "_id": str(app.id),
            "name": app.name,
            "display_name": app.display_name,
        }

        sequence = {
            "_id": str(sequence.id),
            "name": sequence.name,
            "task_name": sequence.task_name,
            "task_id": str(sequence.task_id),
        }
    elif app_id:
        find.append(AppLog.app_id == app_id)
        app = await Application.get(app_id)

        app = {
            "_id": str(app.id),
            "name": app.name,
            "display_name": app.display_name,
        }
        sequence = None
    else:
        app = None
        sequence = None

    if cur:
        find.append(AppLog.t > cur)

    logs = (
        await AppLog.find(*find)
        .limit(limit)
        .sort(("t", SortDirection.DESCENDING))
        .to_list()
    )[::-1]

    return {
        "logs": [
            [
                log.t,
                log.body,
                log.severity,
                str(log.app_id) if app_id is None else "",
                str(log.sequence_id) if sequence_id is None else "",
                str(log.id),
            ]
            for log in logs
        ],
        "cur": cur,
        "limit": limit,
        "app": app,
        "sequence": sequence,
    }
