from typing import *

import fastapi
from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

import server.internal.telephonist.events as events_internal
from server.internal.auth.dependencies import ResourceKey, UserToken
from server.models.auth import TokenModel
from server.models.common import Identifier, Pagination
from server.models.telephonist import Application, Event, EventSource
from server.utils.common import QueryDict

router = fastapi.APIRouter(tags=["events"], prefix="/events")


class EventsFilter(BaseModel):
    event_type: Optional[str]
    receiver: Optional[PydanticObjectId]


class EventsPagination(Pagination):
    ordered_by_options = {"event_type", "_id"}


@router.get("/", dependencies=[UserToken()])
async def get_events(
    pagination: EventsPagination = Depends(),
    filter_data=QueryDict(EventsFilter),
):
    find = []

    if filter_data.event_type:
        find.append(Event.event_type == filter_data.event_type)
    if filter_data.receiver:
        find.append(In(Event.receivers, filter_data.receiver))
    return await pagination.paginate(Event, filter_condition=find)


class PublishEventRequest(BaseModel):
    name: str
    related_task: Optional[Identifier]
    data: Optional[Any]
    on_behalf_of_app: Optional[PydanticObjectId]


@router.post("/publish", description="Publish event")
async def publish_event_endpoint(
    request: Request,
    body: PublishEventRequest = Body(...),
    user_token: Optional[TokenModel] = UserToken(required=False),
    rk: ResourceKey = ResourceKey.Depends("application"),
):
    if user_token is None:
        source_type = EventSource.APPLICATION
        app = await Application.find_by_key(rk.resource_key)
        if app.app_host_id:
            raise HTTPException(401, "this applications belongs to the application host")
        source_id = app.id

    else:
        source_type = EventSource.USER
        source_id = user_token.sub
    event = Event(
        source_id=source_id,
        source_type=source_type,
        event_type=body.name,
        data=body.data,
        publisher_ip=request.client.host,
        related_task=body.related_task,
    )
    await event.save()
    await events_internal.publish_event(event)
    return {"details": "Published"}
