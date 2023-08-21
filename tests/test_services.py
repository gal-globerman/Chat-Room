import asyncio
import time
from datetime import datetime
from unittest import mock

import pytest
from asyncpg import Connection, Pool
from redis.asyncio import Redis

from app import repos, services
from app.domain import entities
from app.domain.notifications import Notification, _NotificationCodes
from app.infra import listeners, sets, streams
from app.services.services import _create_token
from tests.conftest import RSAKeyPair


def test_create_token(rsa_key_pair: RSAKeyPair):
    token = _create_token("asdf", rsa_key_pair.private_key, 3600)
    assert token


def test_token_is_expired(rsa_key_pair: RSAKeyPair):
    token = _create_token("asdf", rsa_key_pair.private_key, exp=1e-10)
    with pytest.raises(services.exceptions.TokenExpired):
        services.is_token_valid(token, rsa_key_pair.public_key)


def test_token_is_not_expired(rsa_key_pair: RSAKeyPair):
    token = _create_token("asdf", rsa_key_pair.private_key, exp=1e10)

    assert services.is_token_valid(token, rsa_key_pair.public_key) == "asdf"


async def test_match_random_user(
    alice_in_db: entities.User,
    bob_in_db: entities.User,
    redis_conn: Redis,
    room_repo: repos.RoomRepository,
    bg_task: None,
):
    rms = sets.RandomMatchingSet(redis_conn)
    ticket_repo = repos.TicketRepository(redis_conn)
    ticket1 = await services.user_matches(alice_in_db.id, rms, ticket_repo, room_repo)
    ticket2 = await services.user_matches(bob_in_db.id, rms, ticket_repo, room_repo)
    async with asyncio.timeout(1):
        while (
            await redis_conn.get(ticket1.key) is None
            or await redis_conn.get(ticket2.key) is None
        ):
            await asyncio.sleep(0.01)
    assert await redis_conn.get(ticket1.key) == await redis_conn.get(ticket2.key)


async def test_match_random_user_but_already_has_thread(
    alice_in_db: entities.User,
    redis_conn: Redis,
    room_repo: repos.RoomRepository,
    bg_task: None,
):
    rms = sets.RandomMatchingSet(redis_conn)
    ticket_repo = repos.TicketRepository(redis_conn)
    await redis_conn.sadd("matching", alice_in_db.id)

    with pytest.raises(services.exceptions.MatchingPermissionDenied):
        await services.user_matches(alice_in_db.id, rms, ticket_repo, room_repo)


async def test_match_random_user_but_already_in_matching(
    alice_in_db: entities.User,
    redis_conn: Redis,
    room_repo: repos.RoomRepository,
    thread_of_alice_and_bob: entities.Thread,
    bg_task: None,
):
    rms = sets.RandomMatchingSet(redis_conn)
    ticket_repo = repos.TicketRepository(redis_conn)

    with pytest.raises(services.exceptions.MatchingPermissionDenied):
        await services.user_matches(alice_in_db.id, rms, ticket_repo, room_repo)


async def test_user_wait_matching_result_and_result_already_set(
    redis_url: str, redis_conn: Redis
):
    ticket_id = "fate"
    user_id = "alice"
    ans = "alice&bob"
    await redis_conn.set(f"user:{user_id}:ticket:{ticket_id}", ans)
    listener = listeners.ValueListerner(redis_url)
    ticket_repo = repos.TicketRepository(redis_conn)
    res = None
    async for thread_id in await services.user_wait_matching_result(
        user_id, ticket_id, ticket_repo, listener
    ):
        res = thread_id
    assert res == ans


async def test_user_wait_matching_result_but_wrong_ticket(
    redis_url: str, redis_conn: Redis
):
    ticket_id = "fate"
    user_id = "alice"
    ans = "alice&bob"
    await redis_conn.set(f"user:{user_id}:ticket:{ticket_id}", ans)
    listener = listeners.ValueListerner(redis_url)
    ticket_repo = repos.TicketRepository(redis_conn)

    with pytest.raises(services.ResourceNotFound):
        async for thread_id in await services.user_wait_matching_result(
            user_id, "xxx", ticket_repo, listener
        ):
            pass


async def test_user_get_tickets(alice: entities.User, redis_conn: Redis):
    assert (
        await services.user_get_tickets(alice.id, repos.TicketRepository(redis_conn))
        == []
    )


async def test_user_delete_ticket(alice: entities.User, redis_conn: Redis):
    await redis_conn.set("user:alice:ticket:asdf", "alice&bob")

    await services.user_delete_ticket(
        alice.id, "asdf", repos.TicketRepository(redis_conn)
    )

    assert (await redis_conn.get("user:alice:ticket:asdf")) is None


async def test_user_delete_ticket2(alice: entities.User, redis_conn: Redis):
    with pytest.raises(services.ResourceNotFound):
        await services.user_delete_ticket(
            alice.id, "asdf", repos.TicketRepository(redis_conn)
        )


async def test_user_delete_ticket3(alice: entities.User, redis_conn: Redis):
    await redis_conn.set("user:alice:ticket:asdf", "None")
    with pytest.raises(services.PermissionDenied):
        await services.user_delete_ticket(
            alice.id, "asdf", repos.TicketRepository(redis_conn)
        )


async def test_get_user_threads(
    alice_in_db: entities.User,
    bob_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_conn: Connection,
):
    room_repo = repos.RoomRepository(db_conn)
    assert await services.user_get_thread_ids(
        alice_in_db, room_repo
    ) == await services.user_get_thread_ids(bob_in_db, room_repo)


async def test_user_leave_thread(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_conn: Connection,
    bg_task: None,
):
    thread_repo = repos.ThreadRepository(db_conn)
    await services.user_leave_thread(
        alice_in_db, thread_of_alice_and_bob.id, thread_repo
    )
    thread = await thread_repo.get(thread_of_alice_and_bob.id)
    assert not thread


async def test_user_leave_thread_but_not_in_thread(
    mallory_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_conn: Connection,
    bg_task: None,
):
    thread_repo = repos.ThreadRepository(db_conn)
    with pytest.raises(services.exceptions.PermissionDenied):
        await services.user_leave_thread(
            mallory_in_db, thread_of_alice_and_bob.id, thread_repo
        )
    thread = await thread_repo.get(thread_of_alice_and_bob.id)
    assert thread
    assert thread.active


async def test_user_leave_thread_but_not_found(
    alice_in_db: entities.User,
    db_conn: Connection,
    bg_task: None,
):
    thread_repo = repos.ThreadRepository(db_conn)
    with pytest.raises(services.exceptions.ResourceNotFound):
        await services.user_leave_thread(alice_in_db, "xxx", thread_repo)


async def test_user_fetch_old_messages(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_conn: Connection,
    redis_conn: Redis,
):
    text = entities.Text(content="Hello world", user_id=alice_in_db.id)
    await redis_conn.xadd(
        thread_of_alice_and_bob.id,
        fields=text.model_dump(exclude_none=True),  # type: ignore
    )
    t = int((time.time() + 1) * 1000)
    room_repo = repos.RoomRepository(db_conn)
    stream = streams.Stream(redis_conn)
    res = await services.user_get_old_messages(
        alice_in_db, thread_of_alice_and_bob.id, t, 1, stream, room_repo
    )
    assert len(res) == 1


async def test_user_fetch_old_messages_but_not_join(
    alice_in_db: entities.User,
    mallory_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    room_repo: repos.RoomRepository,
    redis_conn: Redis,
):
    text = entities.Text(content="Hello world", user_id=alice_in_db.id)
    await redis_conn.xadd(
        thread_of_alice_and_bob.id,
        fields=text.model_dump(exclude_none=True),  # type: ignore
    )
    t = int(time.time() * 1000)
    stream = streams.Stream(redis_conn)
    with pytest.raises(services.exceptions.PermissionDenied):
        await services.user_get_old_messages(
            mallory_in_db, thread_of_alice_and_bob.id, t, 1, stream, room_repo
        )


async def test_user_listen_messages_success(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    room_repo: repos.RoomRepository,
    redis_conn: Redis,
):
    text = entities.Text(content="Hi alice", user_id="")
    entry_id = await redis_conn.xadd(
        thread_of_alice_and_bob.id,
        fields=text.model_dump(exclude_none=True),  # type: ignore
    )
    offsets = {str(thread_of_alice_and_bob.id): int(entry_id.split("-")[0]) - 1000}
    listener = streams.Stream(redis_conn)
    listener.set_offsets(offsets)
    mock_checker = mock.AsyncMock()
    mock_checker.check_keep_going.side_effect = [True, False]

    data = []
    async for msg in services.user_listen_messages(
        mock_checker, alice_in_db, listener, room_repo
    ):
        data.append(msg.content)
    assert data == ["Hi alice"]


async def test_user_listen_messages_but_get_eot(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    room_repo: repos.RoomRepository,
    redis_conn: Redis,
):
    text1 = entities.EndofThreadMessage()
    text2 = entities.Text(content="Hi alice", user_id="")
    for text in [text1, text2]:
        await redis_conn.xadd(
            thread_of_alice_and_bob.id,
            fields=text.model_dump(exclude_none=True),  # type: ignore
        )
    offsets = {str(thread_of_alice_and_bob.id): int(time.time() - 1)}
    listener = streams.Stream(redis_conn)
    listener.set_offsets(offsets)
    mock_checker = mock.AsyncMock()
    mock_checker.check_keep_going.side_effect = [True, False]

    async for msg in services.user_listen_messages(
        mock_checker, alice_in_db, listener, room_repo
    ):
        assert False


async def test_user_listen_messages_but_delete_user_itself_leave(
    alice_in_db: entities.User,
    bob_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    room_repo: repos.RoomRepository,
    redis_conn: Redis,
):
    text1 = entities.MemberLeavedMessage(who=alice_in_db.id)
    text2 = entities.Text(content="Hi alice", user_id="")
    for text in [text1, text2]:
        await redis_conn.xadd(
            thread_of_alice_and_bob.id,
            fields=text.model_dump(exclude_none=True),  # type: ignore
        )
    offsets = {str(thread_of_alice_and_bob.id): int(time.time() - 1)}
    listener = streams.Stream(redis_conn)
    listener.set_offsets(offsets)
    mock_checker = mock.AsyncMock()
    mock_checker.check_keep_going.side_effect = [True, False]

    async for msg in services.user_listen_messages(
        mock_checker, alice_in_db, listener, room_repo
    ):
        assert False


async def test_user_listen_messages_but_not_join(
    mallory_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    room_repo: repos.RoomRepository,
    redis_conn: Redis,
):
    offsets = {
        str(thread_of_alice_and_bob.id): int(datetime.utcnow().timestamp() * 1000)
    }
    listener = streams.Stream(redis_conn)
    listener.set_offsets(offsets)
    mock_checker = mock.AsyncMock()
    mock_checker.check_keep_going.side_effect = [True, False]
    with pytest.raises(services.exceptions.PermissionDenied):
        async for _ in services.user_listen_messages(
            mock_checker, mallory_in_db, listener, room_repo
        ):
            pass


async def test_user_send_message(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_pool: Pool,
    redis_conn: Redis,
    bg_task: None,
):
    thread = thread_of_alice_and_bob
    alice = alice_in_db
    await services.user_send_message(alice, "Hi", thread.id, db_pool)
    await asyncio.sleep(0.01)
    assert await redis_conn.xlen(thread.id) == 1


async def test_user_send_message_but_mallory_not_join(
    mallory_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_pool: Pool,
    redis_conn: Redis,
    bg_task: None,
):
    thread = thread_of_alice_and_bob
    mallory = mallory_in_db
    with pytest.raises(
        services.exceptions.MessagingPermissionDenied, match="user not join"
    ):
        await services.user_send_message(mallory, "Hello world", thread.id, db_pool)
    assert await redis_conn.xlen(thread.id) == 0


async def test_user_send_message_but_thread_not_exist(
    alice_in_db: entities.User,
    thread_of_alice_and_bob: entities.Thread,
    db_pool: Pool,
    redis_conn: Redis,
    bg_task: None,
):
    thread = thread_of_alice_and_bob
    alice = alice_in_db
    with pytest.raises(
        services.exceptions.MessagingPermissionDenied, match="thread deleted"
    ):
        await services.user_send_message(alice, "Hello world", "xxx", db_pool)
    assert await redis_conn.xlen(thread.id) == 0


@mock.patch(
    "app.services.services.Loop.__bool__", mock.MagicMock(side_effect=[True, False])
)
async def test_user_listen_notification():
    mock_stream = mock.Mock()

    class AsyncIter:
        def __init__(self):
            self.stop = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.stop:
                raise StopAsyncIteration
            self.stop = True
            return Notification(code=_NotificationCodes.THREAD_LEAVED, time=time.time())

    mock_stream.listen.return_value = AsyncIter()
    async for n in services.user_listen_notification(mock_stream):
        assert n.code == _NotificationCodes.THREAD_LEAVED
