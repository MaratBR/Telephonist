import asyncio

import motor.motor_asyncio
import nanoid

from server.common.models import Application
from server.database import init_database


async def main():
    client = motor.motor_asyncio.AsyncIOMotorClient()
    await init_database(client)

    for i in range(1000):
        uid = nanoid.generate()
        await Application(
            name=f"application_{uid}", display_name=f"Application {uid}"
        ).insert()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
