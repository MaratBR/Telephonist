import time
from datetime import datetime
from typing import *

import fastapi
from beanie import PydanticObjectId
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.background import BackgroundTasks
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket

from server.internal.auth.dependencies import AccessToken
from server.internal.auth.schema import bearer, require_bearer
from server.internal.channels import WSTicket, WSTicketModel, get_channel_layer
from server.internal.channels.hub import ws_controller
from server.internal.telephonist import realtime
from server.internal.telephonist.utils import CG
from server.models.auth import User
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
    related_task: Optional[str]
    event_key: Optional[str]
    app_id: Optional[PydanticObjectId]
    limit: Optional[int] = Field(gt=1, lt=5000)
    before: Optional[datetime]


class EventsPagination(Pagination):
    default_order_by = "created_at"
    descending_by_default = True
    ordered_by_options = {"event_type", "related_task", "created_at", "_id"}


@router.get("")
async def get_events(
    pagination: EventsPagination = Depends(),
    filter_data=QueryDict(EventsFilter),
):
    find = []

    if filter_data.app_id:
        find.append(Event.app_id == filter_data.app_id)
    if filter_data.event_key:
        find.append(Event.event_key == filter_data.event_key)
    else:
        if filter_data.event_type:
            find.append(Event.event_type == filter_data.event_type)
        if filter_data.related_task:
            find.append(Event.related_task == filter_data.related_task)

    return await pagination.paginate(Event, filter_condition=find)


class PublishEventRequest(BaseModel):
    name: Identifier
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def publish_event(event: Event):
    await event.insert()
    await realtime.notify_event(event)


@router.post("/publish", description="Publish event")
async def publish_event_endpoint(
    request: Request,
    body: PublishEventRequest = Body(...),
    rk: str = Depends(require_bearer),
):
    if realtime.is_reserved_event(body.name):
        raise HTTPException(422, f"event type '{body.name}' is reserved for internal use")
    app = await Application.find_by_key(rk)
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
        if seq.state.is_finished:
            raise HTTPException(409, "the sequence you try to publish to is marked as finished")

        update = {}
        if seq.frozen:
            update["frozen"] = False
        if len(update) != 0:
            await seq.update(update)
            await realtime.on_sequences_updated(seq.app_id, update, [seq.id])

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
    request: Request,
    body: CreateSequence = Body(...),
    rk: str = Depends(require_bearer),
):
    app = await Application.find_by_key(rk)
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
    await publish_event(
        Event(
            sequence_id=sequence.id,
            related_task=body.related_task,
            event_type=realtime.START_EVENT,
            event_key=f"{realtime.START_EVENT}@{body.related_task}",
            publisher_ip=request.client.host,
            app_id=app.id,
        )
    )
    await realtime.on_sequence_updated(sequence)
    return {"_id": sequence.id}


class FinishSequence(BaseModel):
    error_message: Optional[str]
    is_skipped: bool = False


@router.post("/sequence/{seq_id}/finish")
async def finish_sequence(
    seq_id: PydanticObjectId, body: FinishSequence = Body(...), rk: str = Depends(require_bearer)
):
    app = await Application.find_by_key(rk)
    if app is None:
        raise HTTPException(401, "not allowed")
    seq = await EventSequence.get(seq_id)
    if seq is None:
        raise HTTPException(404, f"sequence with id {seq_id} not found")
    if seq.app_id != app.id:
        raise HTTPException(
            401, f"sequence {seq_id} does not belong to the application {app.name} ({app.id})"
        )
    if seq.state.is_finished:
        raise HTTPException(409, f"sequence {seq_id} is already finished")
    if body.is_skipped:
        seq.state = EventSequenceState.SKIPPED
    elif body.error_message:
        seq.state = EventSequenceState.FAILED
    else:
        seq.state = EventSequenceState.SUCCEEDED
    seq.meta = {}
    await seq.replace()
    await realtime.on_sequence_updated(seq)
    return {"detail": f"Sequence {seq_id} is now finished"}


@router.put("/sequence/{seq_id}/meta")
async def update_sequence_meta(
    seq_id: PydanticObjectId,
    new_meta: Dict[str, Any] = Body(...),
    rk: str = Depends(require_bearer),
):
    app = await Application.find_by_key(rk)
    if app is None:
        raise HTTPException(401, "this application does not exist")
    seq = await EventSequence.get(seq_id)
    if seq is None:
        raise HTTPException(404, "sequence not found")
    if seq.app_id != app.id:
        raise HTTPException(401, "this sequence does not belong to this application")
    # TODO disallow updating meta when sequence is finished?
    await seq.update({"meta": new_meta})
    await realtime.on_sequence_meta_updated(seq, new_meta)
    return {"detail": "Metadata has been updated"}


@router.get("/{event_id}", dependencies=[AccessToken()])
async def get_event(event_id: PydanticObjectId):
    event = await Event.get(event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    return event
