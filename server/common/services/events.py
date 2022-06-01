import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException

from server.common.channels import get_channel_layer
from server.common.channels.layer import ChannelLayer
from server.common.models import AppBaseModel, Identifier
from server.common.transit import dispatch
from server.common.transit.transit import BatchConfig, mark_handler
from server.database import Application, Counter, Event, EventSequence
from server.database.sequence import EventSequenceState
from server.dependencies import get_client_ip

_logger = logging.getLogger("telephonist.api.events")

START_EVENT = "start"
STOP_EVENT = "stop"
FROZEN_EVENT = "frozen"
UNFROZEN_EVENT = "unfrozen"
CANCELLED_EVENT = "cancelled"
FAILED_EVENT = "failed"
SUCCEEDED_EVENT = "succeeded"


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


class NewEvent(AppBaseModel):
    id: PydanticObjectId


class EventService:
    def __init__(
        self,
        client_ip: str = Depends(get_client_ip),
        channel_layer: ChannelLayer = Depends(get_channel_layer),
    ):
        self._channel_layer = channel_layer
        self._client_ip = client_ip

    async def create_event(
        self, app: Application, descriptor: EventDescriptor, ip_address: str
    ):
        if descriptor.sequence_id:
            seq = await EventSequence.get(descriptor.sequence_id)
            if seq is None or seq.app_id != app.id:
                raise HTTPException(
                    401,
                    "the sequence you try to publish to does not exist or does"
                    " not belong to the current application",
                )
            if seq.state.is_finished:
                raise HTTPException(
                    409,
                    "the sequence you try to publish to is marked as finished",
                )
            event_key = f"{seq.task_name}/{descriptor.name}"
            task_name = seq.task_name
        else:
            event_key = f"{app.name}/_/{descriptor.name}"
            task_name = None

        event = Event(
            app_id=app.id,
            event_type=descriptor.name,
            event_key=event_key,
            data=descriptor.data,
            publisher_ip=ip_address,
            task_name=task_name,
            sequence_id=descriptor.sequence_id,
        )
        await event.insert()
        await dispatch(NewEvent(id=event.id))
        return event

    async def notify_events(self, *events: Event):
        for event in events:
            _logger.debug(
                f"notifying about events {event.event_key} ({event})"
            )
            groups = [
                f"m/appEvents/{event.app_id}",
                f"e/key/{event.event_key}",
            ]
            if event.sequence_id:
                groups.append(f"m/sequenceEvents/{event.sequence_id}")
            await self._channel_layer.groups_send(
                groups,
                "new_event",
                event,
            )

    @staticmethod
    async def apply_sequence_updates_on_event(event: Event):
        assert event.sequence_id is not None, "sequence_id must be not-None"
        seq = await EventSequence.get(event.sequence_id)
        if seq.frozen:
            seq.frozen = False
            await seq.save_changes()

    async def create_start_event(self, sequence: EventSequence) -> Event:
        return await self.create_sequence_event(sequence, START_EVENT)

    async def create_stop_event(self, sequence: EventSequence) -> Event:
        return await self.create_sequence_event(sequence, STOP_EVENT)

    async def create_sequence_event(
        self, sequence: EventSequence, event_name: str
    ) -> Event:
        start_event = Event(
            sequence_id=sequence.id,
            task_name=sequence.task_name,
            event_type=event_name,
            event_key=f"{sequence.task_name}/{event_name}",
            publisher_ip=self._client_ip,
            app_id=sequence.app_id,
        )
        await start_event.insert()
        await dispatch(NewEvent(id=start_event.id))
        return start_event


class EventsEventHandlers:
    @mark_handler(batch=BatchConfig(max_batch_size=5000, delay=3))
    async def on_new_events(self, events: list[NewEvent]):
        await Counter.inc_counter("events", len(events))


async def orphan_old_sequences():
    q = EventSequence.find(
        EventSequence.state == EventSequenceState.FROZEN,
        EventSequence.state_updated_at
        <= datetime.utcnow() - timedelta(days=1),
    )
    count = await q.count()
    if count == 0:
        return
    _logger.warning(f"detected {count} frozen sequences older than 1 day")
    await q.update(
        {
            "$set": {
                "state": EventSequenceState.ORPHANED,
                "state_updated_at": datetime.utcnow(),
            }
        }
    )
