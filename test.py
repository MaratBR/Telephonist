import asyncio
import time

from server.internal.transit import transit_instance


@transit_instance.register(max_batch_size=100000, delay=4)
async def on_int_event(value: list[int]):
    pass


i = 0
avg = 0
total = 0


async def main():
    asyncio.get_event_loop().run_in_executor(None, printer)
    await asyncio.sleep(1.5)
    global i, total, avg
    for j in range(1, 20000000000000):
        i = j
        v = time.time()
        await transit_instance.dispatch(i)
        elapsed = time.time() - v
        total += elapsed
        avg = total / i

    await asyncio.sleep(100)


def printer():
    print("printer")
    while True:
        print(f"\ravg={avg * 1000}\tcalls={i}\ttotal={total * 1000}\t", end="")
        time.sleep(1)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
