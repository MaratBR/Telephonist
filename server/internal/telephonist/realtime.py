from typing import *

from beanie import Document, PydanticObjectId
from loguru import logger
from pydantic import BaseModel

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG
from server.models.auth import User
from server.models.telephonist import (
    Application,
    Event,
    EventSequence,
    EventSequenceState,
)

EventSourceType = Union[User, Application]

START_EVENT = "start"
STOP_EVENT = "stop"


def is_reserved_event(event_type: str):
    return event_type in (START_EVENT, STOP_EVENT)


async def notify_event(event: Event):
    logger.debug("publishing event {event}", event=event)
    await get_channel_layer().groups_send(
        [
            CG.application_events(event.app_id),
            CG.events(event_type=event.event_type, task_name=event.related_task or "_"),
            CG.events(event_type=event.event_type),
            CG.events(task_name=event.related_task or "_"),
        ],
        "new_event",
        event,
    )


async def publish_entry_update(entry_type: str, entry_id: str, entry: dict):
    await get_channel_layer().groups_send(
        CG.entry(entry_type, entry_id),
        "entry_update",
        {"entry_name": entry_type, "id": entry_id, "entry": entry},
    )


class EntryUpdate(BaseModel):
    id: Any
    entry_name: str
    entry: Any


async def publish_entry_updates(groups: List[str], updates: List[EntryUpdate]):
    await get_channel_layer().groups_send(groups, "entry_updates", {"updates": updates})


async def on_sequences_updated(
    app_id: PydanticObjectId, update: dict, sequences: List[PydanticObjectId]
):
    await publish_entry_updates(
        [CG.app(app_id)],
        [EntryUpdate(id=seq_id, entry_name="event_sequence", entry=update) for seq_id in sequences],
    )


async def on_sequence_meta_updated(seq: EventSequence, meta: Dict[str, Any]):
    await publish_entry_updates(
        [CG.app(seq.app_id), CG.entry("event_sequence", seq.id)],
        [EntryUpdate(id=seq.id, entry_name="event_sequence", entry={"meta": meta})],
    )
