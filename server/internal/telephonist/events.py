from typing import *

from server.internal.channels import get_channel_layer
from server.internal.telephonist.utils import ChannelGroups
from server.models.auth import User
from server.models.telephonist import Application, Event, EventSource

EventSourceType = Union[User, Application]


def publish_task_event(
        task_name: str,
        event_subtype: str,
        source: EventSource,
        source_ip: Optional[str] = None,
        data: Optional[Any] = None,
) -> Awaitable[Event]:
    return publish_event(event_subtype + '@' + task_name, source, source_ip, data, task_name)


async def publish_event(event: Event) -> Event:
    await get_channel_layer().groups_send(
        [ChannelGroups.EVENTS, ChannelGroups.event(event.event_type),
         ChannelGroups.task_events(event.related_task_type) if event.related_task_type else ChannelGroups.GLOBAL_EVENTS],
        'new_event',
        dict(event_type=event.event_type, source_ip=event.publisher_ip, source_id=event.source_id, data=event.data,
             related_task=event.related_task_type, source_type=event.source_type, created_at=event.id.generation_time))
    return event


async def publish_entry_update(entry_type: str, entry_id: str, entry: dict):
    await get_channel_layer().groups_send(
        ChannelGroups.entry(entry_type, entry_id), 'entry_update',
        {'entry_name': 'app', 'id': entry_id, 'entry': entry})
