import logging
from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID

from beanie import PydanticObjectId
from fastapi import HTTPException

from server.internal.channels import get_channel_layer
from server.internal.telephonist import CG
from server.internal.transit import dispatch, register_handler
from server.internal.transit.transit import BatchConfig
from server.models.common import AppBaseModel, Identifier
from server.models.telephonist import (
    ApplicationTask,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.models.telephonist.counter import Counter

_logger = logging.getLogger("telephonist.api.events")

START_EVENT = "start"
STOP_EVENT = "stop"
FROZEN_EVENT = "frozen"
UNFROZEN_EVENT = "unfrozen"
CANCELLED_EVENT = "cancelled"
FAILED_EVENT = "failed"
SUCCEEDED_EVENT = "succeeded"

# region publishing event


def is_reserved_event(event_type: str):
    return event_type in (
        START_EVENT,
        STOP_EVENT,
        FROZEN_EVENT,
        UNFROZEN_EVENT,
        CANCELLED_EVENT,
        FAILED_EVENT,
        SUCCEEDED_EVENT,
    )


class EventDescriptor(AppBaseModel):
    name: Identifier
    data: Optional[Any]
    sequence_id: Optional[PydanticObjectId]


async def create_event(
    app_id: PydanticObjectId, descriptor: EventDescriptor, ip_address: str
):
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


async def notify_events(*events: Event):
    for event in events:
        groups = [
            CG.monitoring.app_events(event.app_id),
            CG.event(event.event_key),
        ]
        if event.sequence_id:
            groups.append(CG.monitoring.sequence_events(event.sequence_id))
        await get_channel_layer().groups_send(
            groups,
            "new_event",
            event,
        )


# endregion


class _SequenceEvent(AppBaseModel):
    sequence_id: PydanticObjectId
    app_id: PydanticObjectId
    task_id: Optional[UUID]


class SequenceUpdated(AppBaseModel):
    sequence: EventSequence


class SequenceCreated(_SequenceEvent):
    pass


class SequenceFinished(_SequenceEvent):
    error: Optional[Any]
    is_skipped: bool


async def apply_sequence_updates_on_event(event: Event):
    assert event.sequence_id is not None, "sequence_id must be not-None"
    seq = await EventSequence.get(event.sequence_id)
    if seq.frozen:
        seq.frozen = False
        await seq.save_changes()


class SequenceDescriptor(AppBaseModel):
    meta: Optional[dict[str, Any]]
    description: Optional[str]
    task_id: Optional[Union[UUID, str]]
    custom_name: Optional[str]


@register_handler(batch=BatchConfig(max_batch_size=100, delay=1))
async def _on_sequence_created(sequences: list[SequenceCreated]):
    await Counter.inc_counter("sequences", len(sequences))
    for m in sequences:
        await get_channel_layer().group_send(
            CG.monitoring.app(m.app_id),
            "sequence",
            {"event": "new", "sequence_id": m.sequence_id},
        )


@register_handler(batch=BatchConfig(max_batch_size=100, delay=1))
async def _on_sequence_updated(sequences: list[SequenceUpdated]):
    for m in sequences:
        await get_channel_layer().group_send(
            CG.monitoring.app(m.sequence.id),
            "sequence",
            {"event": "update", "sequence": m.sequence},
        )


@register_handler(batch=BatchConfig(max_batch_size=100, delay=1))
async def _on_sequence_finished(sequences: list[SequenceFinished]):
    failed_sequences = 0
    for m in sequences:
        if m.error:
            failed_sequences += 1
        await get_channel_layer().group_send(
            CG.monitoring.app(m.app_id),
            "sequence",
            {
                "event": "finished",
                "sequence_id": m.sequence_id,
                "error": m.error,
                "is_skipped": m.is_skipped,
            },
        )

    await Counter.inc_counter("failed_sequences", failed_sequences)
    await Counter.inc_counter("finished_sequences", len(sequences))


async def create_sequence_and_start_event(
    app_id: PydanticObjectId, descriptor: SequenceDescriptor, ip_address: str
) -> tuple[EventSequence, Event]:
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

    # create and publish "start" event
    start_event = Event(
        sequence_id=sequence.id,
        task_name=sequence.task_name,
        event_type=START_EVENT,
        event_key=f"{START_EVENT}@{sequence.task_name}"
        if sequence.task_name
        else START_EVENT,
        publisher_ip=ip_address,
        app_id=sequence.app_id,
    )
    await start_event.insert()
    return sequence, start_event


class FinishSequence(AppBaseModel):
    error_message: Optional[str]
    is_skipped: bool = False


async def finish_sequence(
    sequence: EventSequence, finish_request: FinishSequence, ip_address: str
) -> list[Event]:
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
    await dispatch(
        SequenceFinished(sequence_id=sequence.id, app_id=sequence.app_id)
    )

    stop_event = (
        CANCELLED_EVENT
        if finish_request.is_skipped
        else FAILED_EVENT
        if finish_request.error_message is not None
        else SUCCEEDED_EVENT
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
            STOP_EVENT,  # generic stop event
        )
    ]

    if finish_request.error_message:
        _logger.warning(
            f"sequence {sequence.name} ({sequence.id}) errored:"
            f" {finish_request.error_message}"
        )

    for event in events:
        await event.insert()

    return events


async def set_sequence_meta(
    sequence: EventSequence, new_meta: dict[str, Any], replace: bool = False
):
    if replace:
        sequence.meta = new_meta
    else:
        sequence.meta.update(new_meta)
    await sequence.save_changes()
