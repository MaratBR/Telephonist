from typing import *

import fastapi
from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.background import BackgroundTasks
from starlette.requests import Request

import server.internal.telephonist.events as events_internal
from server.internal.auth.dependencies import ResourceKey, UserToken
from server.models.auth import TokenModel
from server.models.common import Identifier, Pagination
from server.models.telephonist import Application, Event, EventSequence
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
    name: Identifier
    related_task: Optional[Identifier]
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def publish_event(event: Event):
    await event.insert()
    await events_internal.notify_event(event)


@router.post("/publish", description="Publish event")
async def publish_event_endpoint(
    request: Request,
    body: PublishEventRequest = Body(...),
    user_token: Optional[TokenModel] = UserToken(required=False),
    rk: ResourceKey = Depends(ResourceKey.optional("application")),
):
    if user_token is None:
        user_id = None
        app = await Application.find_by_key(rk.key)
        app_id = app.id
        if app.app_host_id:
            raise HTTPException(401, "this applications belongs to the application host")
    else:
        app_id = None
        user_id = user_token.sub
    event_key = f"{body.name}@{body.related_task}" if body.related_task else body.name

    if body.sequence_id and app_id is not None:
        seq = await EventSequence.get(body.sequence_id)
        if seq is None or seq.app_id != app_id:
            raise HTTPException(
                401,
                "the sequence you try to publish to does not exist or does not belong to the"
                " current application",
            )

    event = Event(
        user_id=user_id,
        app_id=app_id,
        event_type=body.name,
        event_key=event_key,
        data=body.data,
        publisher_ip=request.client.host,
        related_task=body.related_task,
        sequence_id=body.sequence_id,
    )
    await publish_event(event)
    return {"details": "Published"}


class CreateSequence(BaseModel):
    name: Optional[str]


@router.post("/sequence")
async def create_sequence(
    body: Optional[CreateSequence] = Body(None),
    rk: ResourceKey = Depends(ResourceKey.required("application")),
):
    app = await Application.find_by_key(rk.key)
    if app is None:
        raise HTTPException(401, "not allowed")
    name = body.name if body else None
    sequence = EventSequence(name=name, app_id=app.id)
    await sequence.save()
    return {"_id": sequence.id}
