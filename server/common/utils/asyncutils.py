__all__ = (
    'merger',
    'AsyncMerger'
)

import asyncio
from asyncio import CancelledError
from typing import AsyncGenerator, Dict, Optional

import nanoid


class AsyncMerger:
    """
    Объеденяет несколько асинхронных генераторов в один. Используется,
    когда необходимо ждать результатов из нескольких источников, представленных
    асинхронными генераторами, например ожидание событий приходящих из разных каналов
    с помощью библиотеки broadcaster
    """

    def __init__(self, queue: asyncio.Queue, *, block_if_empty: bool = False):
        self._cancelling = False
        self._run_count = 0
        self._id_counter = 1
        self._queue = queue
        self._tasks: Dict[str, asyncio.Task] = {}
        self._block_if_empty = block_if_empty

    def add(self, generator: AsyncGenerator, task_id: Optional[str] = None) -> int:
        """
        Добавляет генератор в список. Создает задачу (task), которая отправляется елементы генератора в
        очередь в цикле.
        :param AsyncGenerator generator: Генератор
        """
        task_id = task_id or nanoid.generate()
        print('add', task_id)
        self._run_count += 1
        print(f'self._run_count = {self._run_count}')
        self._tasks[task_id] = asyncio.create_task(self._drain(task_id, generator))
        self._id_counter += 1
        return task_id

    def remove(self, task_id: str):
        print('remove', task_id)
        task = self._tasks.get(task_id)
        if task is not None:
            del self._tasks[task_id]
            task.cancel()
            self._run_count -= 1
            print(f'self._run_count = {self._run_count}')

    async def _drain(self, task_id: str, generator: AsyncGenerator):
        try:
            async for item in generator:
                await self._queue.put((False, item))
        except Exception as e:
            if isinstance(e, CancelledError):
                return
            if not self._cancelling:
                await self._queue.put((True, e))
            else:
                raise
        finally:
            if task_id in self._tasks:
                # задача не была отменена
                self._run_count -= 1
                del self._tasks[task_id]
                print(f'self._run_count = {self._run_count}')

    async def __aiter__(self):
        try:
            while not self._cancelling and (self._run_count > 0 or self._block_if_empty):
                raised, next_item = await self._queue.get()
                if raised:
                    raise next_item
                yield next_item
            print(f'cancelling AsyncMerger self._cancelling={self._cancelling} self._run_count={self._run_count}')
        finally:
            self._cancel()

    def stop(self):
        """
        Останавливает (если точнее начинает остановку) всех задач для
        всех генераторов. Задачи остановятся не сразу, а через некоторое время
        после вызова функции.
        :return:
        """
        self._cancel()

    def _cancel(self):
        if self._cancelling:
            return
        self._cancelling = True
        for t in self._tasks.values():
            if not t.done():
                t.cancel()


merger = AsyncMerger
