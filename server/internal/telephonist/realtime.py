from typing import *
from uuid import UUID

from beanie import PydanticObjectId

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG
from server.models.auth import User
from server.models.common import AppBaseModel
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
                CG.events(
                    event_type=event.event_type,
                    task_name=event.task_name or "_",
                ),
            ],
            "new_event",
            event,
        )


class EntryUpdate(AppBaseModel):
    id: Any
    entry_type: str
    entry: Any


async def on_sequences_updated(
    app_id: PydanticObjectId, sequences: List[PydanticObjectId], update: dict
):
    await get_channel_layer().group_send(
        CG.monitoring.app(app_id),
        "sequences",
        {"sequences": sequences, "update": update},
    )


async def on_sequence_meta_updated(seq: EventSequence, meta: Dict[str, Any]):
    await get_channel_layer().group_send(
        CG.monitoring.app(seq.app_id),
        "sequence_meta",
        {
            "id": seq.id,
            "meta": meta,
        },
    )


async def on_sequence_updated(seq: EventSequence):
    await get_channel_layer().group_send(
        CG.monitoring.app(seq.app_id),
        "sequence",
        {"id": seq.id, "update": seq.dict(by_alias=True, exclude={"id"})},
    )


async def on_connection_info_changed(connection_info: ConnectionInfo):
    await get_channel_layer().groups_send(
        [
            CG.monitoring.app(connection_info.app_id),
            CG.app(connection_info.app_id),
        ],
        "connection",
        connection_info.dict(by_alias=True),
    )


async def on_application_task_updated(task: ApplicationTask):
    await get_channel_layer().group_send(
        CG.monitoring.app(task.app_id),
        "task",
        task.dict(by_alias=True),
    )


async def on_application_task_deleted(task_id: UUID, app_id: PydanticObjectId):
    await get_channel_layer().groups_send(
        [CG.entry("application", app_id), CG.app(app_id)],
        "task_deleted",
        {
            "app_id": app_id,
            "id": task_id,
        },
    )


async def on_application_disabled(app_id: PydanticObjectId, disabled: bool):
    await get_channel_layer().group_send(
        CG.app(app_id), "app", {"id": app_id, "update": {"disabled": disabled}}
    )
    await get_channel_layer().group_send(
        CG.monitoring.app(app_id),
        "app_disabled",
        {"id": app_id, "disabled": disabled},
    )
