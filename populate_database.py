import asyncio
import os
import sys
from functools import wraps

from pymongo.errors import DuplicateKeyError

from server.database import init_database
from server.models.telephonist import (
    Application,
    ApplicationTask,
    AppLog,
    EventSequence,
    EventSequenceState,
)
from server.models.telephonist.task import TaskBody, TaskTrigger


def catch_duplicate_errors(fn):
    @wraps(fn)
    async def new_fn(*args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except DuplicateKeyError:
            return

    return new_fn


@catch_duplicate_errors
async def populate_application(name: str):
    app = Application(
        name=name,
        display_name=name.capitalize().replace("_", " "),
    )
    await app.insert()

    tasks = [
        ApplicationTask(
            app_id=app.id,
            name=f"exec_task",
            display_name='Task of type "exec"',
            app_name=name,
            qualified_name=f"{name}/exec_task",
            body=TaskBody(type="exec", value='echo "Hello World!"'),
            triggers=[
                TaskTrigger(name="fsnotify", body="/home"),
            ],
        ),
        ApplicationTask(
            app_id=app.id,
            name=f"exec_task",
            display_name='Task of type "script"',
            app_name=name,
            qualified_name=f"{name}/script_task",
            body=TaskBody(
                type="script", value='#!/bin/bash\necho "Hello World!"\nenv'
            ),
            triggers=[
                TaskTrigger(name="fsnotify", body="/home"),
            ],
        ),
        ApplicationTask(
            app_id=app.id,
            name=f"exec_task",
            display_name='Task of type "arbitrary"',
            app_name=name,
            qualified_name=f"{name}/arbitrary_task",
            body=TaskBody(
                type="arbitrary",
                value={"some_value": 42, "some_other_value": "lorem"},
            ),
            triggers=[
                TaskTrigger(name="fsnotify", body="/home"),
            ],
        ),
    ]
    for task in tasks:
        await task.insert()
        sequences = [
            EventSequence(
                name=f"Failed sequence ({task.qualified_name})",
                task_id=task.id,
                app_id=task.app_id,
                task_name=task.qualified_name,
                description="this is a failed sequence",
                error="Something went wrong",
                state=EventSequenceState.FAILED,
            ),
            EventSequence(
                name=f"Successful sequence ({task.qualified_name})",
                app_id=task.app_id,
                task_id=task.id,
                task_name=task.qualified_name,
                description="this is a successful sequence",
                state=EventSequenceState.SUCCEEDED,
            ),
            EventSequence(
                name=f"Frozen sequence ({task.qualified_name})",
                task_id=task.id,
                app_id=task.app_id,
                task_name=task.qualified_name,
                description="this sequence is frozen",
                state=EventSequenceState.FROZEN,
            ),
            EventSequence(
                name=f"In-progress sequence ({task.qualified_name})",
                task_id=task.id,
                app_id=task.app_id,
                task_name=task.qualified_name,
                description="this sequence is in progress and has no metadata",
                state=EventSequenceState.IN_PROGRESS,
            ),
            EventSequence(
                name=f"In-progress sequence ({task.qualified_name})",
                task_id=task.id,
                app_id=task.app_id,
                task_name=task.qualified_name,
                description="this sequence is in progress and has metadata",
                state=EventSequenceState.IN_PROGRESS,
                meta={
                    "progress": 34.56,
                    "steps_total": 12,
                    "steps_done": 4,
                    "description": (
                        "Assembling the assembler so we can assemle more"
                        " assemblers for all of your assemling needs"
                    ),
                },
            ),
        ]


async def clean_database():
    for m in [ApplicationTask, Application, EventSequence]:
        await m.delete_all()


async def populate():
    await init_database()
    await clean_database()
    await populate_application("test_application_1")
    await populate_application("test_application_2")
    await populate_application("test_application_3")


if __name__ == "__main__":
    if os.environ.get("TELEPHONIST_POPULATION") != "I KNOW WHAT I AM DOING":
        print("WARNING!!!", file=sys.stderr)
        print(
            "This script will COMPLETELY clear the database and then populate"
            " with data for testing",
            file=sys.stderr,
        )
        print(
            'You must set TELEPHONIST_POPULATION env variable to "I KNOW WHAT'
            ' I AM DOING" to proceed',
            file=sys.stderr,
        )
        exit(0)
    asyncio.get_event_loop().run_until_complete(populate())
