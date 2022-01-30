from typing import *

from beanie import PydanticObjectId
from pydantic import BaseModel

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG
from server.models.auth import User
from server.models.telephonist import (
    Application,
    ApplicationTask,
    ConnectionInfo,
    Event,
    EventSequence,
)

EventSourceType = Union[User, Application]

START_EVENT = "start"
STOP_EVENT = "stop"
CANCELLED_EVENT = "cancelled"
FAILED_EVENT = "failed"
SUCCEEDED_EVENT = "succeeded"


def is_reserved_event(event_type: str):
    return event_type in (START_EVENT, STOP_EVENT)


async def notify_events(*events: Event):
    for event in events:
        await get_channel_layer().groups_send(
            [
                CG.application_events(event.app_id),
                CG.events(event_type=event.event_type, task_name=event.task_name or "_"),
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


async def on_application_task_updated(task: ApplicationTask):
    await publish_entry_update(
        [CG.entry("application", task.app_id), CG.app(task.app_id)],
        EntryUpdate(id=task.id, entry_type="application_task", entry=task),
    )


async def on_application_task_deleted(task_id: PydanticObjectId, app_id: PydanticObjectId):
    await publish_entry_update(
        [CG.entry("application", app_id), CG.app(app_id)],
        EntryUpdate(id=task_id, entry_type="application_task", entry=None),
    )


async def on_application_disabled(app_id: PydanticObjectId, disabled: bool):
    await get_channel_layer().group_send(CG.app(app_id), "app_disabled", {"disabled": disabled})
    await publish_entry_update(
        [CG.entry("application", app_id)],
        EntryUpdate(id=app_id, entry_type="application", entry={"disabled"}),
    )
