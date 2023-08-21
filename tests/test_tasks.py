import asyncio
from unittest import mock

from redis.asyncio import Redis

from app.bus import EventBus
from app.infra.matchers import RandomMatcher
from app.tasks import TaskExecutor


async def test_random_matcher_run_by_task_executor(bus: EventBus, redis_conn: Redis):
    async with TaskExecutor(bus), TaskExecutor(RandomMatcher(redis_conn)):
        pass


async def test_random_match_while_set_has_only_one_user(
    bus: EventBus, redis_conn: Redis
):
    await redis_conn.sadd("rms", "alice:ticket1")
    await redis_conn.sadd("matching", "alice")
    async with TaskExecutor(bus), TaskExecutor(
        RandomMatcher(redis_conn, stop_while_empty=True)
    ):
        pass

    assert await redis_conn.get("ticket1") is None
    assert await redis_conn.sismember("matching", "alice")


@mock.patch("app.domain.entities.Thread.from_pair")
async def test_random_match_task(
    mock_from_pair,
    bus: EventBus,
    redis_conn: Redis,
):
    await redis_conn.sadd("rms", "alice:ticket1")
    await redis_conn.sadd("rms", "bob:ticket2")
    await redis_conn.sismember("matching", "alice")
    await redis_conn.sismember("matching", "bob")

    async with TaskExecutor(bus), TaskExecutor(RandomMatcher(redis_conn)):
        while await redis_conn.scard("rms") != 0:
            await asyncio.sleep(0.0)

    assert await redis_conn.scard("rms") == 0
    assert await redis_conn.scard("matching") == 0
    mock_from_pair.assert_called_once()
