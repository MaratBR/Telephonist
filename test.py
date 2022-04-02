import asyncio

import motor.motor_asyncio
import nanoid

from server.database import (
    Application,
    ApplicationTask,
    Event,
    EventSequence,
    init_database,
)
from server.settings import DebugSettings, use_settings


async def main():
    use_settings(DebugSettings)
    client = motor.motor_asyncio.AsyncIOMotorClient()
    await init_database(client)
    # await create_applications(1)
    n = 5
    await EventSequence.delete_all()
    await Application.delete_all()
    await ApplicationTask.delete_all()
    await Event.delete_all()

    for i in range(n):
        app = Application(
            name=f"application_{i}", display_name=f"Application {i}"
        )
        await app.insert()
        await ApplicationTask(
            app_id=app.id,
        )


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
