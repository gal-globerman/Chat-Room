import abc
import asyncio
import contextlib


class BackgroundTask:
    @abc.abstractmethod
    async def stop(self) -> None:
        pass

    @abc.abstractmethod
    async def __call__(self) -> None:
        pass


@contextlib.asynccontextmanager
async def TaskExecutor(back_ground_task: BackgroundTask):
    task = asyncio.create_task(back_ground_task())
    try:
        yield
    finally:
        await back_ground_task.stop()
        await task
