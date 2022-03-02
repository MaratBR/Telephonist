from fastapi import APIRouter

from server.internal.auth.dependencies import AccessToken
from server.models.telephonist import EventSequence, EventSequenceState
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
async def get_status():
    active_sequences = await EventSequence.find(
        EventSequence.state == EventSequenceState.IN_PROGRESS
    ).count()
    return {
        "sequences": {
            "in_progress": active_sequences,
        }
    }
