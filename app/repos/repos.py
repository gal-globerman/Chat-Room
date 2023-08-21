from datetime import datetime
from typing import List, Optional, Set

from asyncpg import Connection
from asyncpg.exceptions import PostgresError
from asyncpg.pool import PoolConnectionProxy
from redis.asyncio import Redis

from app.domain import entities, tickets, types
from app.repos import exceptions


class UserRepository:
    def __init__(self, conn: Connection | PoolConnectionProxy) -> None:
        self.conn = conn

    async def add(self, user: entities.User) -> None:
        try:
            await self.conn.execute(
                """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
                user.id,
                user.secret.get_secret_value(),
                datetime.utcnow(),
            )
        except PostgresError as e:
            raise exceptions.RepositoryError(e) from e

    async def _get(
        self, id: Optional[str] = None, secret: Optional[types.UserSecret] = None
    ) -> Optional[entities.User]:
        if id is not None:
            field = "id"
            arg = id
        elif secret is not None:
            field = "secret"
            arg = secret.get_secret_value()
        else:
            raise ValueError
        try:
            res = await self.conn.fetchrow(
                f"""SELECT id, secret FROM public.user WHERE active AND {field}=$1""",
                arg,
            )

            return entities.User(**res) if res is not None else None
        except PostgresError as e:
            raise exceptions.RepositoryError from e

    async def get(self, id: str) -> Optional[entities.User]:
        return await self._get(id=id)

    async def get_by_secret(self, secret: types.UserSecret) -> Optional[entities.User]:
        return await self._get(secret=secret)


class ThreadRepository:
    def __init__(self, conn: Connection | PoolConnectionProxy) -> None:
        self.conn = conn

    async def add(self, thread: entities.Thread) -> None:
        async with self.conn.transaction():
            await self.conn.execute(
                "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
                thread.id,
                datetime.utcnow(),
            )
            for user_id, _ in thread.members.items():
                await self.conn.execute(
                    "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
                    thread.id,
                    user_id,
                    datetime.utcnow(),
                    thread.active,
                )

    async def get(self, id: str) -> entities.Thread | None:
        thread_record = await self.conn.fetchrow(
            "SELECT id, created_at FROM public.thread WHERE id=$1", id
        )
        room_records = await self.conn.fetch(
            "SELECT user_id, active FROM public.room WHERE active AND thread_id=$1", id
        )
        if thread_record is None or not room_records:
            return None
        member_ids = [room["user_id"] for room in room_records]
        members = {mid: entities.Member(id=mid) for mid in member_ids}
        return entities.Thread(id=thread_record["id"], members=members)


class RoomRepository:
    def __init__(self, conn: Connection | PoolConnectionProxy) -> None:
        self.conn = conn

    async def list_ids(self, user_id: str) -> List[types.ThreadID]:
        records = await self.conn.fetch(
            "SELECT thread_id FROM public.room WHERE active AND user_id=$1", user_id
        )
        return [r["thread_id"] for r in records]

    async def delete(self, user_id: str, thread_id: str) -> None:
        await self.conn.execute(
            "UPDATE public.room SET active=FALSE WHERE user_id=$1 AND thread_id=$2",
            user_id,
            thread_id,
        )

    async def exist(self, user_id: str, thread_id: str) -> bool:
        return bool(
            await self.conn.fetchval(
                "SELECT 1 FROM public.room WHERE user_id=$1 and thread_id=$2 AND active",
                user_id,
                thread_id,
            )
        )


class TicketRepository:
    def __init__(self, redis: Redis):
        self.r = redis

    async def get(
        self, user_id: types.UserID, ticket_id: types.TicketID
    ) -> Optional[tickets.MatchingTicket]:
        thread_id = await self.r.get(f"user:{user_id}:ticket:{ticket_id}")
        if thread_id is None:
            return None
        return tickets.MatchingTicket(
            user_id=user_id, id=ticket_id, thread_id=str(thread_id)
        )

    async def add(self, ticket: tickets.MatchingTicket):
        await self.r.set(f"user:{ticket.user_id}:ticket:{ticket.id}", ticket.thread_id)
        if ticket.matched_thread is not None:
            # for retention and searching `search_by_thread_id`
            await self.r.sadd(f"thread_tickets:{ticket.matched_thread}", ticket.id)

    async def list_ids(self, user_id: str) -> List[types.TicketID]:
        ids = list(
            map(
                lambda key: key.split(":")[-1],
                await self.r.keys(pattern=f"user:{user_id}:ticket:*"),
            )
        )
        return ids

    async def delete(self, user_id: types.UserID, ticket_id: types.TicketID):
        await self.r.delete(f"user:{user_id}:ticket:{ticket_id}")

    async def search_by_thread_id(
        self, thread_id: types.ThreadID
    ) -> Set[types.TicketID]:
        return await self.r.smembers(f"thread_tickets:{thread_id}")
