from typing import *

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import ChannelGroups
from server.models.auth import User
from server.models.telephonist import Application, Event

EventSourceType = Union[User, Application]


async def publish_event(event: Event) -> Event:
    subscribers = await Application.find_subscribed_id(event.event_type)
    channels = [
        *map(ChannelGroups.app_events, subscribers),
        ChannelGroups.EVENTS,
        ChannelGroups.event(event.event_type),
        ChannelGroups.task_events(event.related_task)
        if event.related_task
        else ChannelGroups.GLOBAL_EVENTS,
    ]
    await get_channel_layer().groups_send(
        channels,
        "new_event",
        {
            "event_type": event.event_type,
            "source_ip": event.publisher_ip,
            "source_id": event.source_id,
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
