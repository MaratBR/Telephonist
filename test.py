import asyncio


async def create_async_gen(number):
    inc = 0
    for i in range(4):
        inc += 1
        await asyncio.sleep(1)
        yield f'{number}_{inc}'


class G:
    def __init__(self):
        self._tasks = []
        self._queue = asyncio.Queue(1)
        self._done = False

    def add(self, gen):
        self._tasks.append(asyncio.create_task(self._drain(gen)))

    async def _drain(self, gen):
        async for i in gen:
            await self._queue.put(i)

    async def __aiter__(self):
        while not all(task.done() for task in self._tasks):
            yield await self._queue.get()


async def main():
    g = G()
    k = 0
    g.add(create_async_gen(k))
    async for i in g:
        print(i)
        k += 1
        g.add(create_async_gen(k))


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
