import datetime

from beanie.odm.enums import SortDirection
from fastapi import APIRouter, Depends, FastAPI

from server.auth.internal.dependencies import (
    require_session,
    validate_csrf_token,
)
from server.database import (
    Application,
    AppLog,
    Counter,
    Event,
    EventSequence,
    EventSequenceState,
    get_database,
)
from server.user_api.applications_router import applications_router
from server.user_api.auth import auth_router
from server.user_api.events_router import events_router
from server.user_api.logs_router import logs_router
from server.user_api.tasks_router import tasks_router
from server.user_api.users_router import users_router
from server.user_api.ws_router import ws_router

authentication_deps = [Depends(require_session), Depends(validate_csrf_token)]

user_api = APIRouter()


user_api.include_router(applications_router, dependencies=authentication_deps)
user_api.include_router(events_router, dependencies=authentication_deps)
user_api.include_router(tasks_router, dependencies=authentication_deps)
user_api.include_router(logs_router, dependencies=authentication_deps)
user_api.include_router(users_router, dependencies=authentication_deps)
user_api.include_router(
    ws_router, prefix="/ws", dependencies=authentication_deps
)
user_api.include_router(auth_router)


@user_api.get("/status")
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
    counters = await Counter.get_counters(
        {"finished_sequences", "sequences", "failed_sequences", "events"}
    )
    failed_sequences = (
        await EventSequence.find(
            EventSequence.state == EventSequenceState.FAILED
        )
        .sort(("_id", SortDirection.DESCENDING))
        .limit(7)
        .to_list()
    )
    return {
        "counters": counters,
        "in_progress_sequences": {
            "count": await EventSequence.find(
                EventSequence.state == EventSequenceState.IN_PROGRESS,
                EventSequence.created_at
                >= datetime.datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
            ).count(),
            "list": await EventSequence.find(
                EventSequence.state == EventSequenceState.IN_PROGRESS,
                EventSequence.created_at
                >= datetime.datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
            )
            .sort(("_id", SortDirection.DESCENDING))
            .limit(20)
            .to_list(),
        },
        "failed_sequences": {
            "count": await EventSequence.find(
                EventSequence.state == EventSequenceState.FAILED
            ).count(),
            "list": failed_sequences,
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
