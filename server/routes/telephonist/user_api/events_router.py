from datetime import datetime
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends
from fastapi.responses import ORJSONResponse
from fastapi_cache.decorator import cache
from starlette.responses import Response

from server.internal.telephonist import Errors
from server.models.common import AppBaseModel, Pagination
from server.models.telephonist import Event, EventSequence
from server.utils.common import QueryDict

events_router = APIRouter(prefix="/events")


class EventsPagination(Pagination):
    default_order_by = "created_at"
    descending_by_default = True
    ordered_by_options = {"event_type", "task_name", "created_at", "_id"}


class EventsFilter(AppBaseModel):
    event_type: Optional[str]
    task_name: Optional[str]
    event_key: Optional[str]
    app_id: Optional[PydanticObjectId]
    before: Optional[datetime]
    sequence_id: Optional[PydanticObjectId]

    def get_filters(self):
        filters = []
        if self.app_id:
            filters.append(Event.app_id == self.app_id)
        if self.sequence_id:
            filters.append(Event.sequence_id == self.sequence_id)
        if self.event_key:
            filters.append(Event.event_key == self.event_key)
        else:
            if self.event_type:
                filters.append(Event.event_type == self.event_type)
            if self.task_name:
                filters.append(Event.task_name == self.task_name)

        return filters


@events_router.get("")
@cache(expire=1)
async def get_events(
    filter_data=QueryDict(EventsFilter),
    pagination: EventsPagination = Depends(),
):
    return Response((
        await pagination.paginate(
            Event, filter_condition=filter_data.get_filters()
        )
    ).json(by_alias=True), headers={"Content-Type": "application/json"})


@events_router.get("/{event_id}")
async def get_event(event_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Event.get(event_id),
        message=f"Event with id={event_id} not found",
    )


@events_router.get("/sequences/{sequence_id}")
async def get_sequence(sequence_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await EventSequence.get(sequence_id),
        message=f"Event sequence with id={sequence_id} not found",
    )
