from typing import Union, Optional

from beanie import PydanticObjectId

from server.auth.models import User
from server.channels import broadcast
from server.telephonist.models import Application, Event, EventMessage


async def publish_event(
        event_type: str,
        source: Union[User, Application],
        source_ip: Optional[str] = None,
        data: Optional[Union[list, dict]] = None
) -> Event:
    event = await Event.create_event(event_type, source, data, source_ip)
    event_data = EventMessage.from_event(event)
    await broadcast.publish_many(
        ['telephonist.events:' + event.event_type, 'telephonist.events'],
        event_data,
    )
    # TODO отправить событие в очередь для всех приложений, которые не доступны
    return event


async def wait_for_ping(app_id: Union[str, PydanticObjectId, Application], timeout_seconds: float):
    await broadcast.publish('internal:app_ping_requests', {
        'app_id': app_id,
        'timeout': timeout_seconds
    })
