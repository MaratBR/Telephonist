from datetime import datetime
from typing import Optional, Union

from beanie import PydanticObjectId
from beanie.odm.enums import SortDirection
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Depends, Query
from fastapi_cache.decorator import cache
from starlette.responses import Response

from server.common.models import AppBaseModel, Pagination
from server.common.utils import Errors
from server.database import (
    Application,
    AppLog,
    ConnectionInfo,
    Counter,
    Event,
    EventSequence,
    EventSequenceState,
)
from server.database.server import Server
from server.utils.common import Querydict

events_router = APIRouter(prefix="/events")


class EventsPagination(Pagination):
    default_order_by = "t"
    descending_by_default = True
    ordered_by_options = {"event_type", "task_name", "t", "_id"}


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
    filter_data=Querydict(EventsFilter),
    pagination: EventsPagination = Depends(),
):
    return Response(
        (
            await pagination.paginate(
                Event, filter_condition=filter_data.get_filters()
            )
        ).json(by_alias=True),
        headers={"Content-Type": "application/json"},
    )


class SequencesPagination(Pagination):
    max_page_size = 100
    descending_by_default = True
    default_order_by = "created_at"


class SequenceFilter(AppBaseModel):
    app_id: Optional[PydanticObjectId]
    state: Optional[Union[EventSequenceState, list[EventSequenceState]]]


@events_router.get("/sequences")
async def get_sequences(
    state: list[EventSequenceState] = Query([]),
    pagination: SequencesPagination = Depends(),
    app_id: Optional[PydanticObjectId] = None,
):
    find = []
    if app_id:
        find.append(EventSequence.app_id == app_id)
    if state:
        find.append(In("state", state))

    if app_id:
        failed = await Counter.get_counter(f"failed_sequences/app/{app_id}")
        total = await Counter.get_counter(f"sequences/app/{app_id}")
        finished = await Counter.get_counter(
            f"finished_sequences/app/{app_id}"
        )
    else:
        failed = await Counter.get_counter(f"failed_sequences")
        total = await Counter.get_counter(f"sequences")
        finished = await Counter.get_counter(f"finished_sequences")

    return {
        **(
            await pagination.paginate(EventSequence, filter_condition=find)
        ).dict(by_alias=True),
        "counters": {"failed": failed, "total": total, "finished": finished},
        "state": state,
    }


@events_router.get("/sequences/{sequence_id}")
async def get_sequence(sequence_id: PydanticObjectId):
    sequence = await EventSequence.get(sequence_id)
    Errors.raise404_if_none(
        sequence,
        message=f"Event sequence with id={sequence_id} not found",
    )
    app = await Application.get(sequence.app_id)
    assert app, "Application must exist"
    server_obj = None
    connection_obj = None
    if sequence.connection_id:
        connection = await ConnectionInfo.get(sequence.connection_id)
        if connection:
            server_obj = await Server.find_one({"ip": connection.ip})
            connection_obj = connection.dict(by_alias=True)
    logs = (
        await AppLog.find(AppLog.sequence_id == sequence.id)
        .sort(("t", SortDirection.DESCENDING))
        .limit(300)
        .to_list()
    )[::-1]
    return {
        **sequence.dict(by_alias=True, exclude={"app_id", "connection_id"}),
        "app": app.dict(
            by_alias=True, include={"id", "deleted_at", "name", "display_name"}
        ),
        "connection": connection_obj,
        "host": server_obj,
    }


@events_router.get("/{event_id}")
async def get_event(event_id: PydanticObjectId):
    return Errors.raise404_if_none(
        await Event.get(event_id),
        message=f"Event with id={event_id} not found",
    )
