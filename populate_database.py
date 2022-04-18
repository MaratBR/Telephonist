import asyncio
import os
import sys
from functools import wraps

from pymongo.errors import DuplicateKeyError

from server.common.channels import start_backplane
from server.common.channels.backplane import InMemoryBackplane
from server.common.internal import create_sequence_and_start_event
from server.common.internal.application import (
    CreateApplication,
    DefineTask,
    create_new_application,
    define_task,
)
from server.common.internal.events import (
    FinishSequence,
    SequenceCreated,
    SequenceDescriptor,
    SequenceFinished,
    finish_sequence,
)
from server.common.transit import dispatch, transit_instance
from server.database import (
    Application,
    Counter,
    Event,
    EventSequence,
    init_database,
)
from server.database.task import ApplicationTask, TaskBody, TaskTypesRegistry
from server.settings import DebugSettings, use_settings


def catch_duplicate_errors(fn):
    @wraps(fn)
    async def new_fn(*args, **kwargs):
        try:
            await fn(*args, **kwargs)
        except DuplicateKeyError:
            return

    return new_fn


async def clear_db():
    for m in (ApplicationTask, Application, Event, EventSequence):
        await m.delete_all()


@catch_duplicate_errors
async def populate_application(name: str):
    app = await create_new_application(
        CreateApplication(
            name=name, display_name=name.capitalize().replace("_", " ")
        )
    )

    for i in range(5, 100, 10):
        await define_task(
            app,
            DefineTask(
                name=f"script_task_sleep_{i}",
                description=f"Script tasks that sleeps for {i} seconds",
                body=TaskBody(
                    type=TaskTypesRegistry.SCRIPT,
                    value=(
                        f"echo Sleeping for {i} seconds\nsleep {i}\necho Done"
                        f" sleeping for {i} seconds"
                    ),
                ),
            ),
        )

    await define_task(
        app,
        DefineTask(
            name="exec_task",
            description="Some exec task",
            body=TaskBody(type=TaskTypesRegistry.EXEC, value="/usr/bin/env"),
        ),
    )
    await define_task(
        app,
        DefineTask(
            name="script_task",
            description="Some script task",
            body=TaskBody(
                type=TaskTypesRegistry.SCRIPT,
                value="echo 123\necho 2\nrm /tmp/testfolder",
            ),
        ),
    )
    arbitrary_task = await define_task(
        app,
        DefineTask(
            name="arbitrary_task",
            description="Some script task",
            body=TaskBody(
                type=TaskTypesRegistry.ARBITRARY,
                value="echo 123\necho 2\nrm /tmp/testfolder",
            ),
        ),
    )
    seq, _ = await create_sequence_and_start_event(
        app.id, SequenceDescriptor(task_id=arbitrary_task.id), "127.0.0.1"
    )
    await dispatch(
        SequenceCreated(
            sequence_id=seq.id, app_id=seq.app_id, task_id=seq.task_id
        )
    )
    await finish_sequence(seq, FinishSequence(), "127.0.0.1")
    await dispatch(
        SequenceFinished(
            sequence_id=seq.id,
            app_id=seq.app_id,
            task_id=seq.task_id,
            is_skipped=False,
        )
    )

    for i in range(10):
        seq, _ = await create_sequence_and_start_event(
            app.id, SequenceDescriptor(task_id=arbitrary_task.id), "127.0.0.1"
        )
        await dispatch(
            SequenceCreated(
                sequence_id=seq.id, app_id=seq.app_id, task_id=seq.task_id
            )
        )
        await finish_sequence(
            seq,
            FinishSequence(error_message="Something went very wrong!"),
            "127.0.0.1",
        )
        await dispatch(
            SequenceFinished(
                sequence_id=seq.id,
                app_id=seq.app_id,
                task_id=seq.task_id,
                error="Something went very wrong!",
                is_skipped=False,
            )
        )

    seq, _ = await create_sequence_and_start_event(
        app.id, SequenceDescriptor(task_id=arbitrary_task.id), "127.0.0.1"
    )
    await dispatch(
        SequenceCreated(
            sequence_id=seq.id, app_id=seq.app_id, task_id=seq.task_id
        )
    )
    await seq.update_meta(
        {
            "steps_total": 400,
            "steps_done": 32,
            "description": "Doing very important things here!",
        }
    )


async def clean_database():
    for m in [ApplicationTask, Application, EventSequence, Event, Counter]:
        await m.delete_all()


async def populate():
    await start_backplane(InMemoryBackplane())
    use_settings(DebugSettings)
    await init_database()
    await clean_database()
    await populate_application("test_application_1")
    await populate_application("test_application_2")
    await populate_application("test_application_3")
    await asyncio.sleep(6)


if __name__ == "__main__":
    if os.environ.get("TELEPHONIST_POPULATION") != "I KNOW WHAT I AM DOING":
        print(os.environ)
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
