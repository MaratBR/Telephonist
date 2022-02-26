import re
from typing import List

from fastapi import APIRouter, Query

from server.models.common import AppBaseModel
from server.models.telephonist import (
    Application,
    ApplicationTask,
    ApplicationView,
)

search_router = APIRouter(prefix="/search")

IDENTIFIER_REGEXP = re.compile(r"^[\d\w%^$#&\-]+$")
QUALIFIED_TASK_NAME_REGEXP = re.compile(r"^[\d\w%^$#&\-]+/[\d\w%^$#&\-]+$")


class SearchEntry(AppBaseModel):
    applications: List[ApplicationView]
    tasks: List[ApplicationTask]


@search_router.get("")
async def search(query: str = Query(...)):
    apps = (
        await Application.find(
            {"$text": {"$search": query}}, Application.NOT_DELETED_COND
        )
        .limit(50)
        .project(ApplicationView)
        .to_list()
    )
    tasks = (
        await ApplicationTask.find(
            {"$text": {"$search": query}}, ApplicationTask.NOT_DELETED_COND
        )
        .limit(50)
        .to_list()
    )

    return SearchEntry(applications=apps, tasks=tasks)
