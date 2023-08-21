import abc
import json
from datetime import datetime, timedelta
from typing import AsyncIterator, List, Set

import jwt
from asyncpg.pool import Pool
from pydantic import SecretStr
from redis.asyncio import Redis

from app import repos
from app.domain import entities, notifications, types
from app.domain.exceptions import MemberNotInThread
from app.domain.tickets import MatchingTicket
from app.infra import listeners, sets, streams
from app.infra.types import MillisecondsTimestamp
from app.services.exceptions import (
    AuthenticationFail,
    MatchingPermissionDenied,
    MessagingPermissionDenied,
    PermissionDenied,
    ResourceNotFound,
    TokenExpired,
)


class Loop:
    def __init__(self) -> None:
        self.loop = True

    def __bool__(self) -> bool:
        return self.loop


async def create_user(user_repo: repos.UserRepository) -> types.UserSecret:
    new_user = entities.User()
    await user_repo.add(new_user)
    return new_user.secret


async def authenticate_user(
    user_secret: str,
    user_repo: repos.UserRepository,
    private_key: SecretStr,
    exp: float = 60,
) -> str:
    user = await user_repo.get_by_secret(types.UserSecret(user_secret))
    if user is None:
        raise AuthenticationFail

    return _create_token(user.id, private_key, exp)


def _create_token(
    user_id: types.UserID | str, private_key: SecretStr, exp: float
) -> str:
    encoded = jwt.encode(
        {"exp": datetime.utcnow() + timedelta(seconds=exp), "id": user_id},
        private_key.get_secret_value(),
        algorithm="RS256",
    )
    return encoded


def is_token_valid(token: str, public_key: SecretStr) -> types.UserID:
    try:
        decoded = jwt.decode(token, public_key.get_secret_value(), algorithms=["RS256"])
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired from e
    return decoded["id"]


async def user_matches(
    user_id: types.UserID,
    rms: sets.RandomMatchingSet,
    ticket_repo: repos.TicketRepository,
    room_repo: repos.RoomRepository,
) -> MatchingTicket:
    if len(await room_repo.list_ids(user_id)) > 0:
        raise MatchingPermissionDenied("Already have room")

    try:
        ticket = MatchingTicket(user_id=user_id)
        await rms.add(ticket)
        await ticket_repo.add(ticket)
        return ticket
    except sets.InMatching as e:
        raise MatchingPermissionDenied from e


async def user_wait_matching_result(
    user_id: types.UserID,
    ticket_id: types.TicketID,
    ticket_repo: repos.TicketRepository,
    listener: listeners.ValueListerner,
) -> AsyncIterator[types.ThreadID]:
    ticket = await ticket_repo.get(user_id, ticket_id)
    if ticket is None:
        raise ResourceNotFound(f"user {user_id} does not have ticket {ticket_id}")

    return listener.listen_forever(ticket.key)


async def user_get_tickets(
    user_id: types.UserID, ticket_repo: repos.TicketRepository
) -> List[MatchingTicket]:
    tickets = []
    for ticket_id in await ticket_repo.list_ids(user_id):
        if (ticket := await ticket_repo.get(user_id, ticket_id)) is not None:
            tickets.append(ticket)

    return tickets


async def user_delete_ticket(
    user_id: types.UserID,
    ticket_id: types.TicketID,
    ticket_repo: repos.TicketRepository,
):
    if ticket := await ticket_repo.get(user_id, ticket_id):
        if ticket.matched_thread:
            await ticket_repo.delete(user_id, ticket_id)
        else:
            raise PermissionDenied
    else:
        raise ResourceNotFound


async def user_get_thread_ids(
    user: entities.User,
    room_repo: repos.RoomRepository,
) -> List[types.ThreadID]:
    return await room_repo.list_ids(user.id)


async def user_leave_thread(
    user: entities.User, thread_id: str, thread_repo: repos.ThreadRepository
) -> None:
    thread = await thread_repo.get(thread_id)
    if thread is None:
        raise ResourceNotFound(f"{thread_id} not found")
    try:
        await thread.leave(user.id)
    except MemberNotInThread as e:
        raise PermissionDenied from e


async def user_get_old_messages(
    user: entities.User,
    thread_id: str,
    timestamp: MillisecondsTimestamp,
    count: int,
    stream: streams.Stream,
    room_repo: repos.RoomRepository,
) -> List[entities.Text]:
    if not await room_repo.exist(user.id, thread_id):
        raise PermissionDenied

    res = []
    async for text in stream.fetch_before(
        thread_id, timestamp, count=count, decoder=streams.thread_stream_decoder
    ):
        res.append(text)
    return res


class AbstractWebSocketHeartbeatChecker(abc.ABC):
    @abc.abstractmethod
    async def check_keep_going(self) -> bool:
        pass


async def user_listen_messages(
    heartbeat_checker: AbstractWebSocketHeartbeatChecker,
    user: entities.User,
    listener: streams.Stream,
    room_repo: repos.RoomRepository,
) -> AsyncIterator[entities.Text]:
    thread_you_listen = set(listener.offsets.keys())
    thread_you_joined = set(await room_repo.list_ids(user.id))
    if thread_you_listen - thread_you_joined:
        raise PermissionDenied

    filter_out: Set[types.ThreadID] = set()
    while await heartbeat_checker.check_keep_going():
        async for message in listener.listen(decoder=streams.thread_stream_decoder):
            if message.thread_id in filter_out:
                continue
            elif message.user_id == entities.User.SYSTEM_USER_ID:
                detail = json.loads(message.content)
                match detail:
                    case (
                        {"flag": entities.Text.EOT}
                        | {"flag": entities.Text.MEMBER_LEAVE, "who": user.id}
                    ):
                        filter_out.add(message.thread_id)  # type: ignore
            else:
                yield message


async def user_send_message(
    user: entities.User,
    content: str,
    thread_id: str,
    db_pool: Pool,
):
    # TODO: Refactor?
    async with db_pool.acquire() as conn:
        thread = await repos.ThreadRepository(conn).get(thread_id)

    if thread is None or not thread.active:
        raise MessagingPermissionDenied("thread deleted")

    try:
        text = entities.Text(content=content, user_id=user.id)
        await thread.add_message(text)
    except MemberNotInThread as e:
        raise MessagingPermissionDenied("user not join") from e


async def user_listen_notification(
    stream: streams.Stream
) -> AsyncIterator[notifications.Notification]:
    loop = Loop()
    while loop:
        async for n in stream.listen(decoder=streams.notification_stream_decoder):
            yield n


async def user_get_current_read_notification_offset(
    user: entities.User, redis: Redis
) -> MillisecondsTimestamp:
    # TODO: Refactor
    if (t := await redis.get(f"{user.id}:last_read_notification_offset")) is not None:
        return int(t)
    else:
        return 0


async def user_update_last_read_notification_offset(
    user: entities.User, redis: Redis, new_offset: MillisecondsTimestamp
):
    # TODO: Refactor
    old_offset = await user_get_current_read_notification_offset(user, redis)
    if new_offset > old_offset:
        await redis.set(f"{user.id}:last_read_notification_offset", new_offset)
    else:
        raise PermissionDenied("timestamp should keep increasing")
