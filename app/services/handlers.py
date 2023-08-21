from asyncpg import Pool
from redis.asyncio import Redis

from app import repos
from app.bus import AbstractHandler
from app.domain import events, notifications
from app.infra import streams


class CreateThread(AbstractHandler):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def __call__(self, event: events.NewThreadCreated):
        async with self.pool.acquire() as conn:
            thread_repo = repos.ThreadRepository(conn)
            await thread_repo.add(event.thread)


class SetTicketResultHandler(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.NewThreadCreated):
        repo = repos.TicketRepository(self.r)
        for t in event.tickets:
            assert t.thread_id
            await repo.add(t)


class NotifyThreadJoined(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.NewThreadCreated):
        n = notifications.ThreadJoinedNotification(
            details={"thread_id": event.thread.id}
        )
        for t in event.tickets:
            await streams.send_notification(self.r, t.user_id, n)


class RemoveMember(AbstractHandler):
    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def __call__(self, event: events.MemberLeaved):
        async with self.pool.acquire() as conn:
            room_repo = repos.RoomRepository(conn)
            await room_repo.delete(event.user_id, event.thread_id)


class ClearTicket(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.MemberLeaved):
        ticket_repo = repos.TicketRepository(self.r)
        for ticket_id in await ticket_repo.search_by_thread_id(event.thread_id):
            await ticket_repo.delete(event.user_id, ticket_id)


class NotifyMemberRemoved(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.MemberLeaved):
        n = notifications.ThreadLeavedNotification(
            details={"thread_id": event.thread_id}
        )
        await streams.send_notification(self.r, event.user_id, n)
        member_leaved_sys_msg = event.sys_msg.model_dump(exclude_none=True)
        await self.r.xadd(event.thread_id, fields=member_leaved_sys_msg)  # type: ignore


class ArchiveThread(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.ThreadClosed):
        eot = event.eot.model_dump(exclude_none=True)
        await self.r.xadd(event.thread_id, fields=eot)  # type: ignore


class MessageAddedHandler(AbstractHandler):
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def __call__(self, event: events.MessageAdded):
        msg = event.msg.model_dump(exclude_none=True)
        await self.r.xadd(event.thread_id, fields=msg)  # type: ignore
