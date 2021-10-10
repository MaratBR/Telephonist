from typing import Union, Optional, TypeVar

from beanie import PydanticObjectId
from fastapi import HTTPException
from starlette import status

from server.auth.models import User
from server.channels import broadcast
from server.telephonist.models import Application, Event, EventMessage

T = TypeVar('T')


def raise404_if_none(value: Optional[T], message: str = 'Not found') -> T:
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, message)
    return value


async def publish_event(
        event_type: str,
        source: Union[User, Application],
        source_ip: Optional[str] = None,
        data: Optional[Union[list, dict]] = None
) -> Event:
    event = await Event.create_event(event_type, source, data, source_ip)
    event_data = EventMessage.from_event(event)
    await broadcast.publish_many(
        ['events:' + event.event_type, 'events'],
        event_data,
    )
    # TODO отправить событие в очередь для всех приложений, которые не доступны
    return event


async def wait_for_ping(app_id: Union[str, PydanticObjectId, Application], timeout_seconds: float):
    await broadcast.publish('internal:app_ping_requests', {
        'app_id': app_id,
        'timeout': timeout_seconds
    })

