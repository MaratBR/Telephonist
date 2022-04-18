import asyncio

import motor.motor_asyncio
import pytest
from beanie import Document, init_beanie


async def do():
    try:
        await asyncio.sleep(1000)
    except asyncio.CancelledError:
        await asyncio.sleep(0.5)


class DocumentWithRevisionTurnedOn(Document):
    num_1: int
    num_2: int

    class Settings:
        use_revision = True
        use_state_management = True


async def test_empty_update():
    doc = DocumentWithRevisionTurnedOn(num_1=1, num_2=2)
    await doc.insert()

    # This fails with RevisionIdWasChanged
    await doc.update({"$set": {"num_1": 1}})


async def main():
    client = motor.motor_asyncio.AsyncIOMotorClient(
        "mongodb://localhost:27017"
    )
    db = client.test_database
    await init_beanie(db, document_models=[DocumentWithRevisionTurnedOn])
    await test_empty_update()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
