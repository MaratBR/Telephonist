from typing import *

from loguru import logger

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import ChannelGroups
from server.models.auth import User
from server.models.telephonist import Application, Event

EventSourceType = Union[User, Application]


async def publish_event(event: Event) -> Event:
    logger.debug("publishing event {event}", event=event)
    await get_channel_layer().groups_send(
        [
            ChannelGroups.EVENTS,
            ChannelGroups.for_event_key(event.event_key),
            ChannelGroups.for_event_type(event.event_type),
            ChannelGroups.for_task_event(event.related_task)
            if event.related_task
            else ChannelGroups.GLOBAL_EVENTS,
        ],
        "new_event",
        {
            "event_type": event.event_type,
            "source_ip": event.publisher_ip,
            "user_id": event.user_id,
            "app_id": event.app_id,
            "data": event.data,
            "related_task": event.related_task,
            "source_type": event.source_type,
            "created_at": event.id.generation_time,
        },
    )
    return event


async def publish_entry_update(entry_type: str, entry_id: str, entry: dict):
    await get_channel_layer().groups_send(
        ChannelGroups.entry(entry_type, entry_id),
        "entry_update",
        {"entry_name": "app", "id": entry_id, "entry": entry},
    )
