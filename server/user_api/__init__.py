from datetime import datetime, timedelta

from beanie.odm.enums import SortDirection
from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import Response

from server import VERSION
from server.auth.dependencies import require_session, validate_csrf_token
from server.auth.models import UserSession
from server.auth.services import SessionsService
from server.database import (
    Application,
    AppLog,
    Counter,
    Event,
    EventSequence,
    EventSequenceState,
    get_database,
)
from server.settings import Settings, get_settings
from server.user_api.applications_router import applications_router
from server.user_api.auth import auth_router
from server.user_api.connections_router import connections_router
from server.user_api.events_router import events_router
from server.user_api.logs_router import logs_router
from server.user_api.tasks_router import tasks_router
from server.user_api.users_router import users_router
from server.user_api.ws_router import ws_router


async def require_session_or_renew(
    request: Request,
    response: Response,
    session: UserSession = Depends(require_session),
    session_service: SessionsService = Depends(),
):
    if session.renew_at and session.renew_at < datetime.utcnow():
        new_session = await session_service.renew(session)
        session_service.set(new_session.id)
        request.scope["app_session"] = new_session
        return new_session
    return session


authentication_deps = [
    Depends(require_session_or_renew),
    Depends(validate_csrf_token),
]

user_api = APIRouter()


user_api.include_router(applications_router, dependencies=authentication_deps)
user_api.include_router(events_router, dependencies=authentication_deps)
user_api.include_router(tasks_router, dependencies=authentication_deps)
user_api.include_router(logs_router, dependencies=authentication_deps)
user_api.include_router(users_router, dependencies=authentication_deps)
user_api.include_router(connections_router, dependencies=authentication_deps)

user_api.include_router(
    ws_router, prefix="/ws", dependencies=authentication_deps
)
user_api.include_router(auth_router)


@user_api.get("/status", dependencies=authentication_deps)
async def get_stats():
    db = get_database()
    db_stats = await db.command("dbStats")
    models = AppLog, Event, EventSequence, Application
    collection_stats = {
        model.get_settings().collection_settings.name: await db.command(
            {"collStats": model.get_settings().collection_settings.name}
        )
        for model in models
    }

    week_ago = (datetime.utcnow() - timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    counters = await Counter.get_counters(
        {"finished_sequences", "sequences", "failed_sequences", "events"}
    )
    return {
        "counters": counters,
        "successful_sequences": {
            "list": await EventSequence.find(
                EventSequence.state == EventSequenceState.SUCCEEDED,
                EventSequence.created_at >= week_ago,
            )
            .sort(("_id", SortDirection.DESCENDING))
            .limit(20)
            .to_list(),
            "count": await EventSequence.find(
                EventSequence.state == EventSequenceState.SUCCEEDED,
                EventSequence.created_at >= week_ago,
            ).count(),
        },
        "in_progress_sequences": {
            "count": await EventSequence.find(
                EventSequence.state == EventSequenceState.IN_PROGRESS,
                EventSequence.created_at >= week_ago,
            ).count(),
            "list": await EventSequence.find(
                EventSequence.state == EventSequenceState.IN_PROGRESS,
                EventSequence.created_at >= week_ago,
            )
            .sort(("_id", SortDirection.DESCENDING))
            .limit(20)
            .to_list(),
        },
        "failed_sequences": {
            "count": await EventSequence.find(
                EventSequence.state == EventSequenceState.FAILED,
                EventSequence.created_at >= week_ago,
            ).count(),
            "list": await EventSequence.find(
                EventSequence.state == EventSequenceState.FAILED
            )
            .sort(("_id", SortDirection.DESCENDING))
            .limit(7)
            .to_list(),
        },
        "db": {
            "stats": {
                "allocated": db_stats["storageSize"],
                "used": db_stats["dataSize"],
                "fs_used": db_stats["fsUsedSize"],
                "fs_total": db_stats["fsTotalSize"],
            },
            "collections": {
                col_name: {
                    "size": stats["size"],
                    "max_size": stats.get("maxSize"),
                    "capped": stats["capped"],
                    "count": stats["count"],
                }
                for col_name, stats in collection_stats.items()
            },
        },
    }


@user_api.get("/summary")
async def summary(
    request: Request, settings: Settings = Depends(get_settings)
):
    now = datetime.now()
    local_now = now.astimezone()
    local_tz = local_now.tzinfo
    local_tzname = local_tz.tzname(local_now)

    return {
        "timezone": {
            "name": local_tzname,
            "offset_seconds": local_tz.utcoffset(local_now).total_seconds(),
        },
        "settings": {
            "cookies_policy": settings.cookies_policy,
            "non_secure_cookies": settings.use_non_secure_cookies,
        },
        "version": VERSION,
        "detected_locale": request.scope.get("locale"),
    }
