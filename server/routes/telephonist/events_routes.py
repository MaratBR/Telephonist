from datetime import datetime
from typing import *

import fastapi
from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

import server.internal.telephonist.events as events_internal
from server.internal.auth.dependencies import AccessToken, ResourceKey
from server.models.auth import UserTokenModel
from server.models.common import Identifier, Pagination
from server.models.telephonist import (
    Application,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.utils.common import QueryDict

router = fastapi.APIRouter(tags=["events"], prefix="/events")


class EventsFilter(BaseModel):
    event_type: Optional[str]
    receiver: Optional[PydanticObjectId]


class EventsPagination(Pagination):
    ordered_by_options = {"event_type", "_id"}


@router.get("/", dependencies=[AccessToken()])
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
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def publish_event(event: Event):
    await event.insert()
    await events_internal.notify_event(event)


@router.post("/publish", description="Publish event")
async def publish_event_endpoint(
    request: Request,
    body: PublishEventRequest = Body(...),
    rk: ResourceKey = Depends(ResourceKey.optional("application")),
):
    app = await Application.find_by_key(rk.key)
    if app is None:
        raise HTTPException(401, "application with given key does not exist")
    if body.sequence_id:
        seq = await EventSequence.get(body.sequence_id)
        if seq is None or seq.app_id != app.id:
            raise HTTPException(
                401,
                "the sequence you try to publish to does not exist or does not belong to the"
                " current application",
            )
        event_key = f"{body.name}@{seq.related_task}"
        related_task = seq.related_task
    else:
        event_key = body.name
        related_task = None

    event = Event(
        app_id=app.id,
        event_type=body.name,
        event_key=event_key,
        data=body.data,
        publisher_ip=request.client.host,
        related_task=related_task,
        sequence_id=body.sequence_id,
    )
    await publish_event(event)
    return {"detail": "Published"}


class CreateSequence(BaseModel):
    meta: Optional[Dict[str, Any]]
    description: Optional[str]
    related_task: Identifier
    custom_name: Optional[str]


@router.post("/sequence")
async def create_sequence(
    body: Optional[CreateSequence] = Body(None),
    rk: ResourceKey = Depends(ResourceKey.required("application")),
):
    app = await Application.find_by_key(rk.key)
    if app is None:
        raise HTTPException(401, "not allowed")
    name = body.custom_name or (body.related_task + datetime.now().strftime(" (%Y.%m.%d %H:%M:%S)"))
    sequence = EventSequence(
        name=name,
        app_id=app.id,
        meta=body.meta,
        description=body.description,
        related_task=body.related_task,
    )
    await sequence.save()
    return {"_id": sequence.id}
