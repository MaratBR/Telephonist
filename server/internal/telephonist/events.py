import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union
from uuid import UUID

from beanie import PydanticObjectId
from fastapi import HTTPException

from server.internal.telephonist import realtime
from server.models.common import AppBaseModel, Identifier
from server.models.telephonist import (
    ApplicationTask,
    Event,
    EventSequence,
    EventSequenceState,
)

_logger = logging.getLogger("telephonist.api.events")


class EventDescriptor(AppBaseModel):
    name: Identifier
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def make_and_validate_event(
    app_id: PydanticObjectId, descriptor: EventDescriptor, ip_address: str
):
    if realtime.is_reserved_event(descriptor.name):
        raise HTTPException(
            422, f"event type '{descriptor.name}' is reserved for internal use"
        )

    if descriptor.sequence_id:
        seq = await EventSequence.get(descriptor.sequence_id)
        if seq is None or seq.app_id != app_id:
            raise HTTPException(
                401,
                "the sequence you try to publish to does not exist or does not"
                " belong to the current application",
            )
        if seq.state.is_finished:
            raise HTTPException(
                409, "the sequence you try to publish to is marked as finished"
            )
        event_key = f"{descriptor.name}@{seq.task_name}"
        task_name = seq.task_name
    else:
        event_key = descriptor.name
        task_name = None

    return Event(
        app_id=app_id,
        event_type=descriptor.name,
        event_key=event_key,
        data=descriptor.data,
        publisher_ip=ip_address,
        task_name=task_name,
        sequence_id=descriptor.sequence_id,
    )


async def publish_events(*events: Event):
    if len(events) == 0:
        return
    _logger.debug(f"publishing events: {events}")
    try:
        await Event.insert_many(list(events))
        await realtime.notify_events(*events)
    except Exception as exc:
        _logger.exception(
            f"failed to publish {len(events)} events: {str(exc)}"
        )
        raise exc


async def apply_sequence_updates_on_event(event: Event):
    assert event.sequence_id is not None, "sequence_id must be not-None"
    seq = await EventSequence.get(event.sequence_id)
    if seq.frozen:
        seq.frozen = False
        await seq.save_changes()
        await realtime.on_sequences_updated(
            seq.app_id, [seq.id], {"frozen": False}
        )


class SequenceDescriptor(AppBaseModel):
    meta: Optional[Dict[str, Any]]
    description: Optional[str]
    task_id: Optional[Union[UUID, str]]
    custom_name: Optional[str]


async def get_sequence(
    sequence_id: PydanticObjectId, app_id: Optional[PydanticObjectId] = None
):
    sequence = await EventSequence.get(sequence_id)
    if sequence is None:
        raise HTTPException(
            404, f"Sequence with id = {sequence_id} does not exist"
        )
    if app_id and sequence.app_id != app_id:
        raise HTTPException(
            401,
            f"Sequence with id = {sequence_id} does not belong to application"
            f" with id = {app_id}",
        )
    return sequence


async def create_sequence(
    app_id: PydanticObjectId, descriptor: SequenceDescriptor
):
    if descriptor.task_id:
        task = await ApplicationTask.find_task(descriptor.task_id)
        if task is None:
            raise HTTPException(
                404,
                f"task with id {descriptor.task_id} never existed or was"
                " deleted",
            )
        if task.app_id != app_id:
            raise HTTPException(
                401,
                f"task {task.id} belongs to application {task.app_id}, not to"
                f" {app_id}, therefore you cannot create a sequence for this"
                " task",
            )
        task_name = task.name
        name = descriptor.custom_name or (
            task_name + datetime.now().strftime(" (%Y.%m.%d %H:%M:%S)")
        )
    else:
        task_name = None
        if descriptor.custom_name is None:
            raise HTTPException(
                422, "you have to either specify task_id or custom_name"
            )
        name = descriptor.custom_name

    sequence = EventSequence(
        name=name,
        app_id=app_id,
        meta=descriptor.meta,
        description=descriptor.description,
        task_name=task_name,
        task_id=descriptor.task_id,
    )
    await sequence.insert()
    return sequence


class FinishSequence(AppBaseModel):
    error_message: Optional[str]
    is_skipped: bool = False


async def finish_sequence(
    sequence: EventSequence, finish_request: FinishSequence, ip_address: str
):
    if sequence.state.is_finished:
        raise HTTPException(409, f"sequence {sequence.id} is already finished")
    if finish_request.is_skipped:
        sequence.state = EventSequenceState.SKIPPED
    elif finish_request.error_message:
        sequence.state = EventSequenceState.FAILED
    else:
        sequence.state = EventSequenceState.SUCCEEDED
    sequence.meta = {}  # TODO ????
    await sequence.replace()

    stop_event = (
        realtime.CANCELLED_EVENT
        if finish_request.is_skipped
        else realtime.FAILED_EVENT
        if finish_request.error_message is not None
        else realtime.SUCCEEDED_EVENT
    )
    events = [
        Event(
            sequence_id=sequence.id,
            task_name=sequence.task_name,
            event_type=event_type,
            event_key=f"{event_type}@{sequence.task_name}"
            if sequence.task_name
            else event_type,
            publisher_ip=ip_address,
            app_id=sequence.app_id,
        )
        for event_type in (
            stop_event,
            realtime.STOP_EVENT,  # generic stop event
        )
    ]

    if finish_request.error_message:
        _logger.warning(
            f"sequence {sequence.name} ({sequence.id}) errored:"
            f" {finish_request.error_message}"
        )

    # publish events and send updates to the clients
    await publish_events(*events)
    await realtime.on_sequence_updated(sequence)


async def set_sequence_meta(
    sequence: EventSequence, new_meta: Dict[str, Any], replace: bool = False
):
    if replace:
        sequence.meta = new_meta
    else:
        sequence.meta.update(new_meta)
    await sequence.save_changes()
    await realtime.on_sequence_meta_updated(sequence, new_meta)
