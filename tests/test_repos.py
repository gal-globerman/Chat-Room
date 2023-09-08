from datetime import UTC, datetime

import pytest
from asyncpg import Connection
from pydantic import SecretStr
from redis.asyncio import Redis

from app import repos
from app.domain import entities, tickets, types


async def test_add_user(db_conn: Connection):
    user = entities.User()
    repo = repos.UserRepository(db_conn)

    await repo.add(user)

    assert await db_conn.fetchval("SELECT 1 FROM public.user WHERE id=$1", user.id) == 1


async def test_add_existing_user(db_conn: Connection):
    user = entities.User()
    repo = repos.UserRepository(db_conn)
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        user.id,
        user.secret.get_secret_value(),
        datetime.now(UTC),
    )

    with pytest.raises(repos.exceptions.RepositoryError):
        await repo.add(user)


async def test_get_user(db_conn: Connection):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        "alice",
        "asdf",
        datetime.now(UTC),
    )
    repo = repos.UserRepository(db_conn)
    user = await repo.get("alice")
    assert user and user.active


async def test_get_user_but_inactive(db_conn: Connection):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at, active) VALUES($1, $2, $3, $4)""",
        "alice",
        "asdf",
        datetime.now(UTC),
        False,
    )
    repo = repos.UserRepository(db_conn)
    assert await repo.get("alice") is None


async def test_get_user_but_not_found(db_conn: Connection):
    repo = repos.UserRepository(db_conn)

    assert await repo.get("xxx") is None


async def test_get_user_by_secret(db_conn: Connection):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        "alice",
        "asdf",
        datetime.now(UTC),
    )
    repo = repos.UserRepository(db_conn)

    assert await repo.get_by_secret(SecretStr("asdf")) is not None


async def test_get_user_by_secret_but_not_found(db_conn: Connection):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        "abc",
        "asdf",
        datetime.now(UTC),
    )
    repo = repos.UserRepository(db_conn)

    assert await repo.get_by_secret(SecretStr("xxx")) is None


async def test_add_new_thread(db_conn: Connection):
    repo = repos.ThreadRepository(db_conn)
    alice = entities.User()
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        alice.id,
        alice.secret.get_secret_value(),
        datetime.now(UTC),
    )
    thread = entities.Thread()
    thread.join(alice.id)
    await repo.add(thread)

    assert await db_conn.fetchval("SELECT 1 from public.thread where id=$1", thread.id)
    assert await db_conn.fetchval(
        "SELECT 1 from public.room where user_id=$1 AND thread_id=$2",
        alice.id,
        thread.id,
    )


async def test_get_thread(db_conn: Connection):
    thread_id = entities.create_id()
    await db_conn.execute(
        "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
        thread_id,
        datetime.now(UTC),
    )
    for user_id in [str(i) for i in range(2)]:
        await db_conn.execute(
            """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
            user_id,
            entities.create_secret().get_secret_value(),
            datetime.now(UTC),
        )
        await db_conn.execute(
            "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
            thread_id,
            user_id,
            datetime.now(UTC),
            True,
        )
    repo = repos.ThreadRepository(db_conn)

    thread = await repo.get(thread_id)

    assert thread
    assert thread.active
    assert thread.has_member(types.UserID("0"))
    assert thread.has_member(types.UserID("1"))


async def test_list_ids_user_room(db_conn: Connection):
    user_id = entities.create_id()
    thread_id = entities.create_id()
    await db_conn.execute(
        "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
        thread_id,
        datetime.now(UTC),
    )
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        user_id,
        entities.create_secret().get_secret_value(),
        datetime.now(UTC),
    )
    await db_conn.execute(
        "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
        thread_id,
        user_id,
        datetime.now(UTC),
        True,
    )
    repo = repos.RoomRepository(db_conn)
    assert await repo.list_ids(user_id) == [thread_id]


async def test_list_ids_user_room_but_empty(db_conn: Connection):
    user_id = entities.create_id()
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        user_id,
        entities.create_secret().get_secret_value(),
        datetime.now(UTC),
    )
    repo = repos.RoomRepository(db_conn)
    assert await repo.list_ids(user_id) == []


async def test_delete_user_room(db_conn: Connection):
    user_id = entities.create_id()
    thread_id = entities.create_id()
    await db_conn.execute(
        "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
        thread_id,
        datetime.now(UTC),
    )
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        user_id,
        entities.create_secret().get_secret_value(),
        datetime.now(UTC),
    )
    await db_conn.execute(
        "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
        thread_id,
        user_id,
        datetime.now(UTC),
        True,
    )
    repo = repos.RoomRepository(db_conn)
    await repo.delete(user_id, thread_id)
    assert (
        await db_conn.fetchval(
            "SELECT 1 FROM public.room WHERE user_id=$1 AND thread_id=$2 AND active",
            user_id,
            thread_id,
        )
        is None
    )


async def test_user_room_exist(db_conn: Connection):
    user_id = entities.create_id()
    thread_id = entities.create_id()
    await db_conn.execute(
        "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
        thread_id,
        datetime.now(UTC),
    )
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        user_id,
        entities.create_secret().get_secret_value(),
        datetime.now(UTC),
    )
    await db_conn.execute(
        "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
        thread_id,
        user_id,
        datetime.now(UTC),
        True,
    )
    repo = repos.RoomRepository(db_conn)

    assert await repo.exist(user_id, thread_id)


async def test_user_room_not_exist(db_conn: Connection):
    repo = repos.RoomRepository(db_conn)
    user_id = entities.create_id()
    assert not await repo.exist(user_id, "xxx")


async def test_add_ticket(redis_conn: Redis):
    repo = repos.TicketRepository(redis_conn)
    ticket = tickets.MatchingTicket(id="fate", user_id="alice", thread_id="alice&bob")

    await repo.add(ticket)

    assert await redis_conn.get(f"user:{ticket.user_id}:ticket:{ticket.id}")


async def test_get_ticket(redis_conn: Redis):
    assert await redis_conn.set("user:alice:ticket:fate", "alice&bob")
    repo = repos.TicketRepository(redis_conn)

    ticket = await repo.get("alice", "fate")

    assert ticket
    assert ticket.thread_id == "alice&bob"


async def test_get_ticket2(redis_conn: Redis):
    repo = repos.TicketRepository(redis_conn)

    ticket = await repo.get("alice", "fate")

    assert ticket is None


async def test_list_ticket_ids(redis_conn: Redis):
    assert await redis_conn.set("user:alice:ticket:fate1", "alice&bob")
    assert await redis_conn.set("user:alice:ticket:fate2", "alice&someguys")

    repo = repos.TicketRepository(redis_conn)

    assert sorted(await repo.list_ids("alice")) == sorted(["fate1", "fate2"])


async def test_delete_ticket(redis_conn: Redis):
    assert await redis_conn.set("user:alice:ticket:fate", "alice&bob")
    repo = repos.TicketRepository(redis_conn)

    await repo.delete("alice", "fate")

    assert await redis_conn.get("user:alice:ticket:fate") is None


async def test_search_ticket_by_thread_id(redis_conn: Redis):
    repo = repos.TicketRepository(redis_conn)
    assert await repo.search_by_thread_id("fate") == set()
    ticket = tickets.MatchingTicket(id="fate", user_id="alice", thread_id="alice&bob")
    await repo.add(ticket)

    assert await repo.search_by_thread_id("alice&bob") == {"fate"}
