import asyncio

from app.bus import EventBus
from app.domain.events import Event
from app.tasks import TaskExecutor


async def test_event_bus_add_handler():
    bus = EventBus()

    @bus.on(Event)
    async def handler(e: Event):
        pass

    assert len(bus.handlers[Event]) == 1


async def test_event_bus_publish_event():
    bus = EventBus()
    await bus.publish(Event())
    assert len(bus) == 1


async def test_event_attach_to_event_bus():
    bus = EventBus()
    event = Event()
    Event.attach(bus)
    assert event._gloabl_bus is not None
    Event.detach(bus)
    assert event._gloabl_bus is None


async def test_event_attach_to_event_bus_2():
    bus = EventBus()
    assert Event._gloabl_bus is None
    async with TaskExecutor(bus):
        await asyncio.sleep(0.0)
        assert Event._gloabl_bus is not None
    assert Event._gloabl_bus is None


async def test_event_bus_handle_event():
    bus = EventBus()
    event = Event()
    async with TaskExecutor(bus):
        await bus.publish(event)
    assert event.handled
    assert len(bus) == 0


async def test_event_bus_handle_event_but_raise_exception():
    bus = EventBus()

    @bus.on(Event)
    async def handler(e: Event):
        raise Exception

    event = Event()
    async with TaskExecutor(bus):
        await bus.publish(event)
    assert not event.handled


async def test_evemt_emit_eager():
    bus = EventBus()
    event = Event()
    event.attach(bus)
    await event.emit()
    assert event.handled


async def test_entity_emit_a_background_event_bus_event():
    bus = EventBus()

    async with TaskExecutor(bus):
        event = Event()
        event.attach(bus)
        await event.emit(eager=False)
        while len(bus) != 0:
            await asyncio.sleep(0)
    assert event.handled
