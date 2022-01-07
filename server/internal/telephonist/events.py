from typing import *

from loguru import logger

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import CG
from server.models.auth import User
from server.models.telephonist import Application, Event

EventSourceType = Union[User, Application]


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
        {
            "event_key": event.event_key,
            "event_type": event.event_type,
            "source_ip": event.publisher_ip,
            "user_id": event.user_id,
            "app_id": event.app_id,
            "data": event.data,
            "related_task": event.related_task,
            "created_at": event.id.generation_time,
        },
    )


async def publish_entry_update(entry_type: str, entry_id: str, entry: dict):
    await get_channel_layer().groups_send(
        CG.entry(entry_type, entry_id),
        "entry_update",
        {"entry_name": "app", "id": entry_id, "entry": entry},
    )
