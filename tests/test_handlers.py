import json

import asyncpg
from asyncpg import Connection, Pool
from redis.asyncio import Redis

from app.domain import entities, events, tickets, types
from app.services import handlers


async def test_create_thread(db_url: str, db_conn: Connection):
    thread = entities.Thread()
    event = events.NewThreadCreated(thread, [])
    async with asyncpg.create_pool(db_url) as pool:
        await handlers.CreateThread(pool)(event)
    assert await db_conn.fetchval("SELECT id from public.thread ") == thread.id


async def test_set_ticket_result_handler(redis_conn: Redis):
    user_id = "alice"
    thread = entities.Thread()
    thread.join(user_id)
    ticket = tickets.MatchingTicket(user_id=user_id, thread_id=thread.id)
    event = events.NewThreadCreated(thread, [ticket])
    await handlers.SetTicketResultHandler(redis_conn)(event)
    assert await redis_conn.get(ticket.key) == thread.id


async def test_notify_thread_joined_handler(
    redis_conn: Redis,
):
    user_id = "alice"
    thread = entities.Thread()
    thread.join(user_id)
    ticket = tickets.MatchingTicket(user_id=user_id, thread_id=thread.id)
    event = events.NewThreadCreated(thread, [ticket])
    await handlers.NotifyThreadJoined(redis_conn)(event)
    assert await redis_conn.xlen(user_id) == 1


async def test_remove_member_handler(
    db_pool: Pool, thread_of_alice_and_bob: entities.Thread, db_conn: Connection
):
    alice = thread_of_alice_and_bob.members["alice"]
    event = events.MemberLeaved(alice.id, thread_of_alice_and_bob.id)
    await handlers.RemoveMember(db_pool)(event)

    assert not await db_conn.fetchval(
        "SELECT 1 FROM public.room WHERE user_id=$1 AND thread_id=$2 AND active",
        alice.id,
        thread_of_alice_and_bob.id,
    )


async def test_clear_ticket_handler(
    redis_conn: Redis, thread_of_alice_and_bob: entities.Thread
):
    ticket_id = "fate"
    alice = thread_of_alice_and_bob.members["alice"]
    event = events.MemberLeaved(alice.id, thread_of_alice_and_bob.id)
    await redis_conn.sadd(f"thread_tickets:{thread_of_alice_and_bob.id}", ticket_id)
    await redis_conn.set(
        f"user:{alice.id}:ticket:{ticket_id}", thread_of_alice_and_bob.id
    )

    await handlers.ClearTicket(redis_conn)(event)

    assert await redis_conn.smembers(f"user:{alice.id}:ticket:{ticket_id}") == set()


async def test_notify_member_leaved_handler(
    thread_of_alice_and_bob: entities.Thread, redis_conn: Redis
):
    alice = thread_of_alice_and_bob.members["alice"]
    event = events.MemberLeaved(alice.id, thread_of_alice_and_bob.id)
    await handlers.NotifyMemberRemoved(redis_conn)(event)

    assert await redis_conn.xlen("alice") == 1

    assert (
        json.loads(
            (await redis_conn.xrevrange(thread_of_alice_and_bob.id, count=1))[0][1][
                "content"
            ]
        )["who"]
        == alice.id
    )


async def test_archive_thread_handler(redis_conn: Redis):
    event = events.ThreadClosed("asdf", entities.EndofThreadMessage())

    await handlers.ArchiveThread(redis_conn)(event)

    assert (await redis_conn.xrevrange("asdf", count=1))[0][1][
        "content"
    ] == '{"flag": "EOT"}'


async def test_message_added(redis_conn: Redis):
    text = entities.Text(user_id=types.UserID("bob"), content="Hello world")
    event = events.MessageAdded("thread0", text)

    await handlers.MessageAddedHandler(redis_conn)(event)

    data = await redis_conn.xread({"thread0": "0"})
    assert data[0][1][0][1]["id"] == text.id
