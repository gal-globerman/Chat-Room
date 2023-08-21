from typing import List

from redis.asyncio import Redis

from app.domain import types
from app.domain.tickets import MatchingTicket


class InMatching(Exception):
    pass


class EmptySet(Exception):
    pass


class EmptyRandomMatchingSet(EmptySet):
    pass


class NotEnoughElements(Exception):
    pass


class RandomMatchingSet:
    def __init__(
        self,
        redis: Redis,
    ) -> None:
        self.set_name = "rms"
        self.matching_set_name = "matching"
        self.r = redis

    @property
    def name(self) -> str:
        return self.set_name

    async def add(self, ticket: MatchingTicket):
        if await self.in_matching(ticket.user_id):
            raise InMatching
        async with self.r.pipeline() as pipeline:
            await pipeline.sadd(self.matching_set_name, ticket.user_id)
            await pipeline.sadd(self.set_name, f"{ticket.user_id}:{ticket.id}")
            await pipeline.execute()

    async def pop(self) -> MatchingTicket:
        elements: List[str] = await self.r.spop(self.set_name, count=1)  # type: ignore
        if len(elements) == 0:
            raise EmptyRandomMatchingSet
        user_id, ticket_id = elements[0].split(":")
        return MatchingTicket(id=ticket_id, user_id=user_id)

    async def pop_pair(self) -> List[MatchingTicket]:
        if await self.r.scard(self.set_name) < 2:
            raise NotEnoughElements
        elements = await self.r.spop(self.set_name, count=2)
        tickets = []
        for e in elements:
            uid, tid = e.split(":")  # type: ignore
            tickets.append(MatchingTicket(id=tid, user_id=uid))  # type: ignore
        return tickets

    async def in_matching(self, user_id: types.UserID) -> bool:
        return bool((await self.r.smismember(self.matching_set_name, user_id))[0])

    async def mark_matched(self, *tickets: MatchingTicket):
        async with self.r.pipeline() as pipeline:
            for ticket in tickets:
                await pipeline.srem(self.matching_set_name, ticket.user_id)
            await pipeline.execute()
