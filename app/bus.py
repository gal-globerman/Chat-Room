from __future__ import annotations

import abc
import logging
from asyncio import Queue
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Self, Type, TypeAlias, TypeVar

from app.tasks import BackgroundTask

logger = logging.getLogger()


class Event:
    _gloabl_bus: Optional[EventBus] = None

    def __init__(self, allow_emit: bool = True) -> None:
        self.allow_emit = allow_emit
        self.handled = False

    @classmethod
    def attach(cls, bus: EventBus):
        if cls._gloabl_bus is not None:
            ValueError("bus already attached")
        cls._gloabl_bus = bus

    @classmethod
    def detach(cls, bus: EventBus):
        if cls._gloabl_bus is not bus:
            ValueError(f"current bus {cls._gloabl_bus} not same bus {bus}")
        cls._gloabl_bus = None

    async def emit(self, eager: bool = True) -> Self:
        if self._gloabl_bus is None:
            logger.warning(f"{self} have not attached bus")
            return self
        if not self.allow_emit:
            logger.warning(f"{self} not allowed to emit")
            return self
        if eager:
            await self._gloabl_bus.handle(self)
        else:
            await self._gloabl_bus.publish(self)
        return self


class StopBusEvent(Event):
    pass


class AbstractHandler(abc.ABC):
    @abc.abstractmethod
    async def __call__(self, e: Any):
        pass


EventHandler: TypeAlias = AbstractHandler | Callable[..., Any]
DecoratedCallable = TypeVar("DecoratedCallable", bound=EventHandler)


class EventBus(BackgroundTask):
    def __init__(self) -> None:
        self.handlers: Dict[Type[Event], List[EventHandler]] = defaultdict(list)
        self.queue: Queue[Event] = Queue()
        self.logger = logging.getLogger()

    def __len__(self) -> int:
        return self.queue.qsize()

    def add_handler(self, event_type: Type[Event], handler: EventHandler) -> Self:
        if handler not in self.handlers[event_type]:
            self.handlers[event_type].append(handler)
        return self

    def on(
        self, event_type: Type[Event]
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_handler(event_type, func)
            return func

        return decorator

    async def publish(self, *events: Event) -> None:
        for event in events:
            await self.queue.put(event)

    async def handle(self, *events: Event) -> None:
        for event in events:
            for handler in self.handlers[type(event)]:
                await handler(event)
            event.handled = True

    async def stop(self):
        await self.queue.put(StopBusEvent())
        await self.queue.join()

    async def __call__(self) -> None:
        Event.attach(self)
        while True:
            event = await self.queue.get()
            if isinstance(event, StopBusEvent):
                self.queue.task_done()
                break
            try:
                await self.handle(event)
            except Exception as e:
                self.logger.exception(e)
            finally:
                self.queue.task_done()
        Event.detach(self)
