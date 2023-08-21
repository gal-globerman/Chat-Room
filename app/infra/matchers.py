from redis.asyncio import Redis

from app.domain.entities import Thread
from app.infra import sets
from app.tasks import BackgroundTask


class RandomMatcher(BackgroundTask):
    def __init__(
        self,
        redis: Redis,
        stop_while_empty: bool = False,
    ) -> None:
        self.stop_while_empty = stop_while_empty
        self.rms = sets.RandomMatchingSet(redis)
        self.stop_loop = False
        self.pubsub = redis.pubsub()
        self.channel = f"__keyspace@0__:{self.rms.name}"

    async def stop(self):
        self.stop_loop = True
        await self.pubsub.unsubscribe(self.channel)

    async def __call__(self):
        need_fetch_old_tickets = True
        async with self.pubsub:
            await self.pubsub.subscribe(self.channel)

            while not self.stop_loop:
                msg = await self.pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=None,  # type: ignore
                )
                if (
                    not (msg is not None and msg["data"] == "sadd")
                    and not need_fetch_old_tickets
                ):
                    continue
                try:
                    ticket1, ticket2 = await self.rms.pop_pair()
                except sets.NotEnoughElements:
                    need_fetch_old_tickets = False
                    if self.stop_while_empty:
                        break
                else:
                    await Thread.from_pair(ticket1, ticket2)
                    await self.rms.mark_matched(ticket1, ticket2)
