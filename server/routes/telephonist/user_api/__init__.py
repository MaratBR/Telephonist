from fastapi import APIRouter

from server.internal.auth.dependencies import AccessToken
from server.routes.telephonist.user_api.applications_router import applications_router
from server.routes.telephonist.user_api.events_router import events_router
from server.routes.telephonist.user_api.ws_router import ws_router

user_api_router = APIRouter(prefix="/user-api", tags=["user-api"], dependencies=[AccessToken()])

user_api_router.include_router(applications_router)
user_api_router.include_router(events_router)
user_api_router.include_router(ws_router)