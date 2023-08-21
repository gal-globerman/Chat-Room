import pytest
from redis.asyncio import Redis

from app.domain.tickets import MatchingTicket
from app.infra import sets


async def test_add_random_matching_set(redis_conn: Redis):
    rms = sets.RandomMatchingSet(redis_conn)
    ticket = MatchingTicket(user_id="alice")
    await rms.add(ticket)

    assert await redis_conn.scard(rms.name) == 1
    assert await redis_conn.scard("matching") == 1


async def test_add_random_matching_set_but_already_in_matching(redis_conn: Redis):
    rms = sets.RandomMatchingSet(redis_conn)
    ticket = MatchingTicket(user_id="alice")
    await rms.add(ticket)

    with pytest.raises(sets.InMatching):
        await rms.add(ticket)


async def test_pop_from_random_matching_set(redis_conn: Redis):
    await redis_conn.sadd("rms", "alice:ticket")
    await redis_conn.sadd("matching", "alice")

    rms = sets.RandomMatchingSet(redis_conn)
    ticket = await rms.pop()

    assert ticket.id == "ticket"
    assert await redis_conn.scard("rms") == 0
    assert await redis_conn.scard("matching") == 1


async def test_pop_from_random_matching_set_but_empty(redis_conn: Redis):
    rms = sets.RandomMatchingSet(redis_conn)
    with pytest.raises(sets.EmptyRandomMatchingSet):
        await rms.pop()


async def test_pop_pair_from_random_matching_set(redis_conn: Redis):
    for i in ["alice", "bob"]:
        await redis_conn.sadd("rms", f"{i}:ticket-{i}")
        await redis_conn.sadd("matching", i)

    rms = sets.RandomMatchingSet(redis_conn)
    ticket1, ticket2 = await rms.pop_pair()

    assert ticket1.id == "ticket-alice"
    assert ticket2.id == "ticket-bob"
    assert await redis_conn.scard("rms") == 0
    assert await redis_conn.scard("matching") == 2


async def test_pop_pair_from_random_matching_set_but_empty(redis_conn: Redis):
    for i in ["alice"]:
        await redis_conn.sadd("rms", f"{i}:ticket-{i}")
        await redis_conn.sadd("matching", i)

    rms = sets.RandomMatchingSet(redis_conn)
    with pytest.raises(sets.NotEnoughElements):
        await rms.pop_pair()


async def test_mark_pair(redis_conn: Redis):
    await redis_conn.sadd("matching", "alice")
    rms = sets.RandomMatchingSet(redis_conn)
    ticket = MatchingTicket(user_id="alice")
    await rms.mark_matched(ticket)
    assert await redis_conn.scard("matching") == 0
