import asyncio
from typing import AsyncIterator

from redis.asyncio import Redis


class ValueListerner:
    def __init__(self, redis_url: str) -> None:
        self.action_type = ["set"]
        self.r = Redis.from_url(redis_url, decode_responses=True)
        self._wait_get_message = asyncio.Event()

    async def listen_forever(
        self, key: str, skip_value: str = "None"
    ) -> AsyncIterator[str]:
        async with self.r.pubsub() as pubsub:
            await pubsub.subscribe(f"__keyspace@0__:{key}")
            _get_data = False
            while not _get_data:
                if (value := await self.r.get(key)) is not None and value != skip_value:
                    yield value
                    _get_data = True
                elif (msg := await self._get_message(pubsub)) and (
                    msg["data"] in self.action_type
                ):
                    continue
        await self.r.aclose()  # type: ignore

    async def _get_message(self, pubsub):
        self._wait_get_message.set()
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=None)
        return msg
