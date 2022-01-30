import logging
from datetime import datetime
from typing import *

import fastapi
from beanie import PydanticObjectId
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from server.internal.auth.dependencies import AccessToken
from server.internal.auth.schema import require_bearer
from server.internal.telephonist import realtime
from server.models.common import Identifier, Pagination
from server.models.telephonist import (
    Application,
    ApplicationTask,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.utils.common import QueryDict

router = fastapi.APIRouter(tags=["events"], prefix="/events")
_logger = logging.getLogger("telephonist.api.events")


class EventsFilter(BaseModel):
    event_type: Optional[str]
    task_name: Optional[str]
    event_key: Optional[str]
    app_id: Optional[PydanticObjectId]
    limit: Optional[int] = Field(gt=1, lt=5000)
    before: Optional[datetime]


class EventsPagination(Pagination):
    default_order_by = "created_at"
    descending_by_default = True
    ordered_by_options = {"event_type", "task_name", "created_at", "_id"}


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
        if filter_data.task_name:
            find.append(Event.task_name == filter_data.task_name)

    return await pagination.paginate(Event, filter_condition=find)


class PublishEventRequest(BaseModel):
    name: Identifier
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def publish_events(*events: Event):
    if len(events) == 0:
        return
    _logger.debug(f"publishing events: {events}")
    try:
        await Event.insert_many(*events)
        await realtime.notify_events(*events)
    except Exception as exc:
        _logger.exception(f"failed to publish {len(events)} events: {str(exc)}")
        raise exc


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

        event_key = f"{body.name}@{seq.task_name}"
        task_name = seq.task_name
    else:
        event_key = body.name
        task_name = None

    event = Event(
        app_id=app.id,
        event_type=body.name,
        event_key=event_key,
        data=body.data,
        publisher_ip=request.client.host,
        task_name=task_name,
        sequence_id=body.sequence_id,
    )
    await publish_events(event)
    return {"detail": "Published"}


@router.get("/sequence")
async def get_sequences():
    sequences = await EventSequence.find().to_list()
    return sequences


class CreateSequence(BaseModel):
    meta: Optional[Dict[str, Any]]
    description: Optional[str]
    task_id: Optional[PydanticObjectId]
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
    if body.task_id:
        task = await ApplicationTask.get_not_deleted(body.task_id)
        if task is None:
            raise HTTPException(404, f"task with id {body.task_id} never existed or was deleted")
        if task.app_id != app.id:
            raise HTTPException(
                401,
                f"task {task.id} belongs to application {task.app_id}, not to {app.id}, therefore"
                " you cannot create a sequence for this task",
            )
        task_name = task.name
        name = body.custom_name or (task_name + datetime.now().strftime(" (%Y.%m.%d %H:%M:%S)"))
    else:
        task_name = None
        if body.custom_name is None:
            raise HTTPException(422, "you have to either specify task_id or custom_name")
        name = body.custom_name

    sequence = EventSequence(
        name=name,
        app_id=app.id,
        meta=body.meta,
        description=body.description,
        task_name=task_name,
        task_id=body.task_id,
    )
    await sequence.save()
    await publish_events(
        Event(
            sequence_id=sequence.id,
            task_name=task_name,
            event_type=realtime.START_EVENT,
            event_key=f"{realtime.START_EVENT}@{task_name}" if task_name else realtime.START_EVENT,
            publisher_ip=request.client.host,
            app_id=app.id,
        )
    )
    await realtime.on_sequence_updated(sequence)
    _logger.info(f"new sequence started: {sequence}")
    return {"_id": sequence.id}


class FinishSequence(BaseModel):
    error_message: Optional[str]
    is_skipped: bool = False


@router.post("/sequence/{seq_id}/finish")
async def finish_sequence(
    request: Request,
    seq_id: PydanticObjectId,
    body: FinishSequence = Body(...),
    rk: str = Depends(require_bearer),
):
    """
    Marks sequence as finished
    :param request: HTTP request
    :param seq_id: ID of the sequence
    :param FinishSequence body: request body
    :param str rk: resource key of the application
    :return: JSON object
    """
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

    stop_event = (
        realtime.CANCELLED_EVENT
        if body.is_skipped
        else realtime.FAILED_EVENT
        if body.error_message is not None
        else realtime.SUCCEEDED_EVENT
    )
    events = [
        Event(
            sequence_id=seq_id,
            task_name=seq.task_name,
            event_type=event_type,
            event_key=f"{event_type}@{seq.task_name}" if seq.task_name else event_type,
            publisher_ip=request.client.host,
            app_id=app.id,
        )
        for event_type in (
            stop_event,
            realtime.STOP_EVENT,  # generic stop event
        )
    ]

    if body.error_message:
        _logger.warning(f"sequence {seq.name} ({seq.id}) errored: {body.error_message}")

    # publish events and send updates to the clients
    await publish_events(*events)
    await realtime.on_sequence_updated(seq)
    return {"detail": f"Sequence {seq_id} is now finished"}


@router.get("/sequence/{seq_id}/events", dependencies=[AccessToken()])
async def get_sequence_events(seq_id: PydanticObjectId):
    if not await EventSequence.find({"_id": seq_id}).exists():
        raise HTTPException(404, f"event sequence {seq_id} does not exist")
    events = await Event.find(Event.sequence_id == seq_id).to_list()
    return events


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
