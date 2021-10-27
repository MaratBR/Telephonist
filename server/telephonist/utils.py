import asyncio
from typing import Union, Optional, TypeVar

from beanie import PydanticObjectId
from fastapi import HTTPException
from starlette import status

from server.auth.models import User
from server.channels import broadcast
from server.telephonist.models import Application, Event, EventMessage, SentEventTrace

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
    subscribed_ids = await Application.find_subscribed_id(event_type)
    await asyncio.gather(
        broadcast.publish_many(
            [
                InternalChannels.event(event_type),
                InternalChannels.EVENTS,
                *map(InternalChannels.app_events, subscribed_ids)
            ],
            event_data,
        ),

        SentEventTrace.add_trace(
            event_type,
            subscribed_ids,
            source.id if isinstance(source, Application) else None
        )
    )
    return event


class InternalChannels:
    EVENTS = 'events'
    APPS = 'apps'

    @classmethod
    def event(cls, name: str):
        return cls.EVENTS + '.' + name

    @classmethod
    def app_events(cls, app_id: Union[str, PydanticObjectId]):
        return cls.APPS + '.' + str(app_id) + '.events'
