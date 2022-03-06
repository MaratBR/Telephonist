from fastapi import APIRouter

from server.database import get_database
from server.models.telephonist import Application, AppLog, Event, EventSequence
from server.models.telephonist.counter import Counter

public_api_router = APIRouter()


@public_api_router.get("/stats")
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
    return {
        "counters": counters,
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
