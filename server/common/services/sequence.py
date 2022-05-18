import logging
from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID

from beanie import PydanticObjectId
from fastapi import Depends, FastAPI, HTTPException

from server.common.channels.layer import ChannelLayer, get_channel_layer
from server.common.models import AppBaseModel
from server.common.services.events import (
    FAILED_EVENT,
    SUCCEEDED_EVENT,
    EventService,
    NewEvent,
)
from server.common.transit import dispatch
from server.common.transit.transit import BatchConfig, mark_handler
from server.database import (
    ApplicationTask,
    ConnectionInfo,
    Counter,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.database.sequence import TriggeredBy


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


class FinishSequence(AppBaseModel):
    error_message: Optional[str]
    metadata: Optional[dict[str, Any]]


class SequenceDescriptor(AppBaseModel):
    meta: Optional[dict[str, Any]]
    description: Optional[str]
    task_id: Union[UUID, str]
    custom_name: Optional[str]
    connection_id: Optional[UUID]
    triggered_by: Optional[TriggeredBy]


class SequenceService:
    def __init__(
        self,
        channel_layer: ChannelLayer = Depends(get_channel_layer),
        event_service: EventService = Depends(),
    ):
        self._channel_layer = channel_layer
        self._logger = logging.getLogger(
            "telephonist.api.services.SequenceService"
        )
        self._event_service = event_service

    async def notify_sequence_changed(self, sequence: EventSequence):
        await self._channel_layer.group_send(
            f"m/seq/{sequence.id}", "sequence", sequence
        )

    async def create_sequence_and_start_event(
        self,
        app_id: PydanticObjectId,
        descriptor: SequenceDescriptor,
        ip_address: str,
    ) -> tuple[EventSequence, Event]:
        if descriptor.connection_id:
            connection = await ConnectionInfo.get(descriptor.connection_id)
            if connection is None:
                raise HTTPException(
                    404,
                    "cannot create sequence for connection id"
                    f" {descriptor.connection_id}: cannot find connection with"
                    " given id",
                )
        task = await ApplicationTask.find_task(descriptor.task_id)
        if task is None:
            raise HTTPException(
                404,
                "cannot create sequence: task with id"
                f" {descriptor.task_id} never existed or was deleted",
            )
        if task.app_id != app_id:
            raise HTTPException(
                401,
                f"cannot create sequence: task {task.id} belongs to"
                f" application {task.app_id}, not to {app_id}, therefore you"
                " cannot create a sequence for this task",
            )
        task_name = task.qualified_name
        name = descriptor.custom_name or (
            task_name + " [" + str(int(datetime.utcnow().timestamp())) + "]"
        )

        sequence = EventSequence(
            name=name,
            app_id=app_id,
            meta=descriptor.meta,
            description=descriptor.description,
            task_name=task_name,
            task_id=descriptor.task_id,
            connection_id=descriptor.connection_id,
            triggered_by=descriptor.triggered_by,
        )
        await sequence.insert()

        return sequence, await self._event_service.create_start_event(sequence)

    async def finish_sequence(
        self,
        sequence: EventSequence,
        finish_request: FinishSequence,
        ip_address: str,
    ) -> list[Event]:
        if sequence.state.is_finished:
            raise HTTPException(
                409, f"sequence {sequence.id} is already finished"
            )
        sequence.finished_at = datetime.utcnow()
        sequence.error = finish_request.error_message
        sequence.state_updated_at = datetime.utcnow()
        if finish_request.error_message:
            sequence.state = EventSequenceState.FAILED
        else:
            sequence.state = EventSequenceState.SUCCEEDED
        sequence.meta = {}
        await sequence.replace()
        stop_event = (
            FAILED_EVENT
            if finish_request.error_message is not None
            else SUCCEEDED_EVENT
        )
        events = [
            Event(
                sequence_id=sequence.id,
                task_name=sequence.task_name,
                task_id=sequence.task_id,
                event_type=event_type,
                event_key=f"{sequence.task_name}/{event_type}"
                if sequence.task_name
                else event_type,
                publisher_ip=ip_address,
                app_id=sequence.app_id,
                data=finish_request.metadata,
            )
            for event_type in (
                stop_event,
                "stop",  # generic stop event
            )
        ]
        for e in events:
            await e.insert()
            await dispatch(NewEvent(id=e.id))

        if finish_request.error_message:
            self._logger.warning(
                f"sequence {sequence.name} ({sequence.id}) errored:"
                f" {finish_request.error_message}"
            )

        return events


class SequenceEventHandlers:
    def __init__(self, app: FastAPI):
        self.app = app

    @mark_handler(batch=BatchConfig(max_batch_size=100, delay=1))
    async def on_sequence_created(self, sequences: list[SequenceCreated]):
        await Counter.inc_counter("sequences", len(sequences))
        for m in sequences:
            await Counter.inc_counter(f"sequences/app/{m.app_id}", 1)
            if m.task_id:
                await Counter.inc_counter(f"sequences/task/{m.task_id}", 1)
            await get_channel_layer(self.app).group_send(
                f"m/app/{m.app_id}",
                "sequence",
                {"event": "new", "sequence_id": m.sequence_id},
            )

    @mark_handler(batch=BatchConfig(max_batch_size=100, delay=1))
    async def on_sequence_updated(self, sequences: list[SequenceUpdated]):
        for m in sequences:
            await get_channel_layer(self.app).groups_send(
                [
                    f"m/sequence/{m.sequence.id}",
                    f"m/app/{m.sequence.app_id}",
                ],
                "sequence",
                {"event": "update", "sequence": m.sequence},
            )

    @mark_handler(batch=BatchConfig(max_batch_size=100, delay=1))
    async def on_sequence_finished(self, sequences: list[SequenceFinished]):
        failed_sequences = 0
        for m in sequences:
            await Counter.inc_counter(f"sequences/app/{m.app_id}", 1)
            if m.error:
                await Counter.inc_counter(
                    f"failed_sequences/app/{m.app_id}", 1
                )
                if m.task_id:
                    await Counter.inc_counter(
                        f"failed_sequences/task/{m.task_id}", 1
                    )
                failed_sequences += 1
            await get_channel_layer(self.app).group_send(
                f"m/app/{m.app_id}",
                "sequence",
                {
                    "event": "finished",
                    "sequence_id": m.sequence_id,
                    "error": m.error,
                },
            )

        await Counter.inc_counter("failed_sequences", failed_sequences)
        await Counter.inc_counter("finished_sequences", len(sequences))
