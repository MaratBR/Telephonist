from typing import *

from beanie import Document, PydanticObjectId
from pydantic import BaseModel

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG
from server.models.auth import User
from server.models.telephonist import (
    Application,
    ConnectionInfo,
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
    await get_channel_layer().groups_send(
        [
            CG.application_events(event.app_id),
            CG.events(event_type=event.event_type, task_name=event.related_task or "_"),
        ],
        "new_event",
        event,
    )


class EntryUpdate(BaseModel):
    id: Any
    entry_type: str
    entry: Any


async def publish_entry_update(groups: List[str], update: EntryUpdate):
    await get_channel_layer().groups_send(groups, "entry_update", update)


async def publish_entry_updates(groups: List[str], updates: List[EntryUpdate]):
    await get_channel_layer().groups_send(groups, "entry_updates", {"updates": updates})


async def on_sequences_updated(
    app_id: PydanticObjectId, update: dict, sequences: List[PydanticObjectId]
):
    await publish_entry_updates(
        [CG.entry("application", app_id)],
        [EntryUpdate(id=seq_id, entry_type="event_sequence", entry=update) for seq_id in sequences],
    )


async def on_sequence_meta_updated(seq: EventSequence, meta: Dict[str, Any]):
    await publish_entry_updates(
        [CG.entry("application", seq.app_id), CG.entry("event_sequence", seq.id)],
        [EntryUpdate(id=seq.id, entry_type="event_sequence", entry={"meta": meta})],
    )


async def on_sequence_updated(seq: EventSequence):
    await publish_entry_update(
        [CG.entry("event_sequence", seq.id), CG.entry("application", seq.app_id)],
        EntryUpdate(id=seq.id, entry_type="event_sequence", entry=seq),
    )


async def on_connection_info_changed(connection_info: ConnectionInfo):
    await publish_entry_update(
        [
            CG.entry("application", connection_info.app_id),
            CG.entry("connection_info", connection_info),
        ],
        EntryUpdate(id=connection_info.id, entry_type="connection_info", entry=connection_info),
    )
