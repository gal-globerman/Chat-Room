import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

from asyncpg import Connection
from fastapi import status
from httpx import AsyncClient
from redis.asyncio import Redis

from app.api import endpoints
from app.domain import entities, tickets
from app.domain.notifications import Notification, _NotificationCodes
from app.infra import streams
from tests.conftest import AsyncWSClient


async def test_index(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == status.HTTP_307_TEMPORARY_REDIRECT


async def test_create_user(client: AsyncClient):
    resp = await client.post("/users")

    assert resp.status_code == status.HTTP_201_CREATED
    assert UUID(resp.json()["secret"])


async def test_aquire_jwt_token(client: AsyncClient, db_conn: Connection):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        "Bob",
        "asdf",
        datetime.utcnow(),
    )

    resp = await client.post("/tokens", json={"secret": "asdf"})

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["access_token"]


async def test_aquire_jwt_token_but_incorrect_password(
    client: AsyncClient, db_conn: Connection
):
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        "Bob",
        "asdf",
        datetime.utcnow(),
    )

    resp = await client.post("/tokens", json={"secret": "xxx"})

    assert resp.status_code == status.HTTP_400_BAD_REQUEST


async def test_get_user_info(bob_client: AsyncClient, bob_in_db):
    resp = await bob_client.get("/users/me")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == bob_in_db.id


async def test_get_user_info_but_no_premission(client: AsyncClient):
    resp = await client.get("/users/me")

    assert resp.status_code == status.HTTP_403_FORBIDDEN


async def test_bob_match_random_user(
    bob_client: AsyncClient,
):
    resp = await bob_client.post("/match")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["ticket_id"]


async def test_bob_match_random_user_repeatedly(
    bob_client: AsyncClient,
):
    await bob_client.post("/match")
    resp = await bob_client.post("/match")
    assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS


async def test_bob_and_alice_match_together(
    alice_client: AsyncClient, bob_client: AsyncClient
):
    alice_ticket = (await alice_client.post("/match")).json()["ticket_id"]
    bob_ticket = (await bob_client.post("/match")).json()["ticket_id"]

    alice_matched_thread = None
    async with alice_client.stream("GET", f"/match/tickets/{alice_ticket}") as resp:
        async for thread_id in resp.aiter_lines():
            alice_matched_thread = thread_id

    bob_matched_thread = None
    async with bob_client.stream("GET", f"/match/tickets/{bob_ticket}") as resp:
        async for thread_id in resp.aiter_lines():
            bob_matched_thread = thread_id

    assert alice_matched_thread
    assert alice_matched_thread == bob_matched_thread


async def test_alice_match_random_user_but_ticket_not_found(
    alice_client: AsyncClient,
):
    async with alice_client.stream("GET", "/match/tickets/xxx") as resp:
        async for thread_id in resp.aiter_lines():
            pass

    assert resp.status_code == status.HTTP_404_NOT_FOUND


@patch(
    "app.api.endpoints.services.user_get_tickets",
    return_value=[
        tickets.MatchingTicket(id="asdf", user_id="alice", thread_id="alice&bob")
    ],
)  # type: ignore
async def test_user_get_tickets(mock_user_get_tickets, alice_client: AsyncClient):
    resp = await alice_client.get("/tickets")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == [{"id": "asdf", "thread_id": "alice&bob"}]


async def test_user_delete_ticket(alice_client: AsyncClient, redis_conn: Redis):
    await redis_conn.set("user:alice:ticket:asdf", "alice&bob")
    resp = await alice_client.delete("/tickets/asdf")
    assert resp.status_code == status.HTTP_204_NO_CONTENT


async def test_user_delete_ticket_but_not_found(alice_client: AsyncClient):
    resp = await alice_client.delete("/tickets/asdf")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_user_delete_ticket_but_permission_denied(
    alice_client: AsyncClient, redis_conn: Redis
):
    await redis_conn.set("user:alice:ticket:asdf", "None")
    resp = await alice_client.delete("/tickets/asdf")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


async def test_alice_and_bob_get_threads(
    alice_client: AsyncClient,
    bob_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
):
    resp1 = await alice_client.get("/threads")
    resp2 = await bob_client.get("/threads")
    assert {"ids": [thread_of_alice_and_bob.id]} == resp1.json() == resp2.json()


async def test_alice_leave_thread(
    alice_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
):
    resp = await alice_client.post(f"/threads/{thread_of_alice_and_bob.id}/leave")
    assert resp.status_code == status.HTTP_200_OK


async def test_alice_leave_thread_but_not_found(
    alice_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
):
    resp = await alice_client.post("/threads/xxx/leave")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_mollory_leave_thread_but_not_join(
    mallory_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
):
    resp = await mallory_client.post(f"/threads/{thread_of_alice_and_bob.id}/leave")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_alice_get_old_message(
    alice_in_db: entities.User,
    alice_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
    redis_conn: Redis,
):
    old_message = entities.Text(user_id=alice_in_db.id, content="Hi bob").model_dump(
        exclude_none=True
    )
    i = await redis_conn.xadd(thread_of_alice_and_bob.id, fields=old_message)  # type: ignore
    now = int(i.split("-")[0])
    resp = await alice_client.get(
        f"/threads/{thread_of_alice_and_bob.id}", params={"t": now}
    )
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["data"]) > 0


async def test_alice_get_old_message_but_without_t_parameter(
    alice_client: AsyncClient,
    thread_of_alice_and_bob: entities.Thread,
):
    resp = await alice_client.get(f"/threads/{thread_of_alice_and_bob.id}")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_message_offset():
    now = datetime.now(timezone.utc).timestamp()
    offsets = endpoints.MesseageListenOffset.model_validate({"stream_name": now})
    assert offsets.model_dump() == {"stream_name": int(now * 1000)}


async def test_listen_message_success(
    alice_in_db: entities.User,
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
    redis_conn: Redis,
):
    thread_id = thread_of_alice_and_bob.id
    ans = [
        entities.Text(user_id=alice_in_db.id, content="Hi bob").model_dump(
            exclude_none=True
        )
    ]
    t = time.time() - 0.1
    for text in ans:
        await redis_conn.xadd(thread_id, fields=text)  # type: ignore

    async with asyncio.timeout(0.1):
        async with alice_ws_client.connect("/messages/down") as ws:
            await ws.send(json.dumps({thread_of_alice_and_bob.id: t}))
            while True:
                if (raw_msg := await ws.recv()) == "PING":
                    await ws.send("PONG")
                else:
                    msg = json.loads(raw_msg)
                    assert msg["text"] == "Hi bob"
                    break
            await ws.close()
            await ws.wait_closed()


async def test_listen_message_but_listen_wrong_thread(
    mallory_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with mallory_ws_client.connect("/messages/down") as ws:
        await ws.send(json.dumps({thread_of_alice_and_bob.id: "0"}))
        await ws.wait_closed()
        assert ws.close_code == 3003


async def test_listen_message_but_no_heartbeat(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with alice_ws_client.connect("/messages/down") as ws:
        await ws.send(json.dumps({thread_of_alice_and_bob.id: "0"}))
        assert await ws.recv() == "PING"
        await ws.wait_closed()


async def test_listen_message_but_wrong_heartbeat(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with alice_ws_client.connect("/messages/down") as ws:
        await ws.send(json.dumps({thread_of_alice_and_bob.id: "0"}))
        assert await ws.recv() == "PING"
        await ws.send("???")
        await ws.wait_closed()
        assert ws.close_code == status.WS_1000_NORMAL_CLOSURE


async def test_listen_message_but_broken_query(
    alice_ws_client: AsyncWSClient,
):
    async with alice_ws_client.connect("/messages/down") as ws:
        await ws.send("{")
        await ws.wait_closed()
        assert ws.close_code == status.WS_1003_UNSUPPORTED_DATA


async def test_listen_message_but_invalid_query(
    alice_ws_client: AsyncWSClient,
):
    async with alice_ws_client.connect("/messages/down") as ws:
        await ws.send(json.dumps({"xxx": "xxx"}))
        await ws.wait_closed()
        assert ws.close_code == status.WS_1003_UNSUPPORTED_DATA


async def test_listen_message_but_close(
    alice_ws_client: AsyncWSClient,
):
    async with alice_ws_client.connect("/messages/down") as ws:
        await ws.send(json.dumps({"xxx": "xxx"}))
        await ws.close()
        await ws.wait_closed()
        assert ws.close_code == status.WS_1000_NORMAL_CLOSURE


async def test_send_text_message(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
    redis_conn: Redis,
):
    data = endpoints.IncomingMessage(text="Hello world", tid=thread_of_alice_and_bob.id)
    async with alice_ws_client.connect("/messages/up") as ws:
        await ws.send(data.model_dump_json())
        await ws.close()
        assert ws.close_code == status.WS_1000_NORMAL_CLOSURE
        await ws.wait_closed()

    async with asyncio.timeout(0.1):
        while await redis_conn.xlen(thread_of_alice_and_bob.id) == 0:
            await asyncio.sleep(0.0)

    assert await redis_conn.xlen(thread_of_alice_and_bob.id) == 1


async def test_send_broken_json_message(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with alice_ws_client.connect("/messages/up") as ws:
        await ws.send("{")
        await ws.wait_closed()
        assert ws.close_code == status.WS_1003_UNSUPPORTED_DATA


async def test_send_invalid_json_message(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    data = {"text": "Hello world"}
    async with alice_ws_client.connect("/messages/up") as ws:
        await ws.send(json.dumps(data))
        await ws.wait_closed()
        assert ws.close_code == status.WS_1003_UNSUPPORTED_DATA


async def test_close_message_websocket_conn(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with alice_ws_client.connect("/messages/up") as ws:
        await ws.close()
        assert ws.close_code == status.WS_1000_NORMAL_CLOSURE
        await ws.wait_closed()


async def test_sned_byte_message(
    alice_ws_client: AsyncWSClient,
    thread_of_alice_and_bob: entities.Thread,
):
    async with alice_ws_client.connect("/messages/up") as ws:
        await ws.send(b"asdf")
        await ws.wait_closed()
        assert ws.close_code == status.WS_1011_INTERNAL_ERROR


@patch("app.services.services.Loop.__bool__", MagicMock(side_effect=[True, False]))
async def test_listen_notification(
    alice_in_db: entities.User, alice_client: AsyncClient, redis_conn: Redis
):
    n = Notification(code=_NotificationCodes.THREAD_LEAVED)
    await streams.send_notification(redis_conn, alice_in_db.id, n)
    res = []
    async with alice_client.stream(
        "GET", "/users/me/notifications", params={"t": time.perf_counter() - 1}
    ) as resp:
        async for chunk in resp.aiter_lines():  # only aiter_lines works for testing
            res.append(json.loads(chunk)["code"])
    assert [_NotificationCodes.THREAD_LEAVED] == res


async def test_get_notification_read_offset(
    alice: entities.User, alice_client: AsyncClient, redis_conn: Redis
):
    millisec_timestamp = int(datetime.now(timezone.utc).timestamp() * 100)
    await redis_conn.set(
        f"{alice.id}:last_read_notification_offset", millisec_timestamp
    )

    resp = await alice_client.get("/users/me/notifications/read-offset")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["offset"] == millisec_timestamp / 1000


async def test_update_notification_read_offset(
    alice: entities.User, alice_client: AsyncClient, redis_conn: Redis
):
    millisec_timestamp = int(datetime.now(timezone.utc).timestamp() * 100)

    resp = await alice_client.patch(
        "/users/me/notifications/read-offset",
        json={"new_offset": millisec_timestamp},
    )

    assert resp.status_code == status.HTTP_200_OK
    assert await redis_conn.get(f"{alice.id}:last_read_notification_offset") == str(
        millisec_timestamp
    )


async def test_update_notification_read_offset_but_offset_not_increment(
    alice: entities.User, alice_client: AsyncClient, redis_conn: Redis
):
    millisec_timestamp = int(datetime.now(timezone.utc).timestamp() * 100)
    await redis_conn.set(
        f"{alice.id}:last_read_notification_offset", millisec_timestamp
    )

    resp = await alice_client.patch(
        "/users/me/notifications/read-offset",
        json={"new_offset": millisec_timestamp - 1},
    )

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert await redis_conn.get(f"{alice.id}:last_read_notification_offset") == str(
        millisec_timestamp
    )
