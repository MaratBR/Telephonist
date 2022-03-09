from beanie.odm.enums import SortDirection
from fastapi import APIRouter

from server.database import get_database
from server.internal.auth.dependencies import AccessToken
from server.models.telephonist import (
    Application,
    AppLog,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.models.telephonist.counter import Counter
from server.routes.telephonist.user_api.applications_router import (
    applications_router,
)
from server.routes.telephonist.user_api.events_router import events_router
from server.routes.telephonist.user_api.logs_router import logs_router
from server.routes.telephonist.user_api.tasks_router import tasks_router
from server.routes.telephonist.user_api.ws_router import ws_router

user_api_router = APIRouter(
    prefix="/user-api", tags=["user-api"], dependencies=[AccessToken()]
)

user_api_router.include_router(applications_router)
user_api_router.include_router(events_router)
user_api_router.include_router(tasks_router)
user_api_router.include_router(logs_router)
user_api_router.include_router(ws_router, prefix="/ws")


@user_api_router.get("/status")
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
    sequences = (
        await EventSequence.find(
            EventSequence.state == EventSequenceState.FAILED
        )
        .sort(("_id", SortDirection.DESCENDING))
        .limit(20)
        .to_list()
    )
    return {
        "counters": counters,
        "failed_sequences": sequences,
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
