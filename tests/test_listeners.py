import asyncio

from redis.asyncio import Redis

from app.infra import listeners


async def test_ticket_listener_listen_forever1(redis_url: str, redis_conn: Redis):
    test_ticket_id = "asdf"
    listener = listeners.ValueListerner(redis_url)
    await redis_conn.set(test_ticket_id, "None")

    async def key_event():
        await listener._wait_get_message.wait()
        await redis_conn.set(test_ticket_id, "ans")

    asyncio.create_task(key_event())

    res = None
    async with asyncio.timeout(0.1):
        async for thread_id in listener.listen_forever(test_ticket_id):
            res = thread_id
    assert res == "ans"


async def test_ticket_listener_listen_forever2(redis_url: str, redis_conn: Redis):
    test_ticket_id = "asdf"
    listener = listeners.ValueListerner(redis_url)
    await redis_conn.set("asdf", "ans")
    res = None
    async with asyncio.timeout(0.1):
        async for thread_id in listener.listen_forever(test_ticket_id):
            res = thread_id
    assert res == "ans"
