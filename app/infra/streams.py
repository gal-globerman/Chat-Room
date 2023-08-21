import asyncio
import json
from datetime import datetime, timezone
from typing import (
    AsyncIterator,
    Callable,
    Dict,
    Optional,
    TypeVar,
)

from redis.asyncio import Redis

from app.domain import entities, notifications
from app.infra import types


def default_decoder(stream: types.StreamName, time: float, entry: dict) -> dict:
    return entry


def notification_stream_decoder(stream: types.StreamName, time: float, entry: dict):
    obj = json.loads(entry["object"])
    obj["time"] = time
    return notifications.Notification.model_validate(obj)


def thread_stream_decoder(stream_name: str, time: float, data: dict) -> entities.Text:
    return entities.Text(
        thread_id=stream_name,
        time=datetime.fromtimestamp(time, tz=timezone.utc),
        **data,
    )


class Stream:
    DecoderReturnT = TypeVar("DecoderReturnT")

    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def fetch_before(
        self,
        stream_name: str,
        timestamp: types.MillisecondsTimestamp,
        *,
        count: int,
        decoder: Callable[
            [types.StreamName, float, dict], DecoderReturnT
        ] = default_decoder,  # type: ignore
        reverse: bool = True,
    ) -> AsyncIterator[DecoderReturnT]:
        res = await self.r.xrevrange(stream_name, max=str(timestamp), count=count)
        if not reverse:
            res.reverse()
        for entry_id, entry in res:
            time = int(entry_id.split("-")[0]) / 1000

            yield decoder(stream_name, time, entry)
            await asyncio.sleep(0.0)

    def set_offsets(self, offsets: Dict[types.StreamName, types.MillisecondsTimestamp]):
        self.offsets = offsets

    async def listen(
        self,
        block: Optional[float] = 1000,
        decoder: Callable[
            [types.StreamName, float, dict], DecoderReturnT
        ] = default_decoder,  # type: ignore
    ) -> AsyncIterator[DecoderReturnT]:
        for stream_name, entrys in await self.r.xread(self.offsets, block=block):
            for entry_id, entry in entrys:
                time = int(entry_id.split("-")[0]) / 1000
                self.offsets[stream_name] = entry_id
                yield decoder(stream_name, time, entry)
                await asyncio.sleep(0.0)


async def send_notification(
    redis: Redis, stream_name: types.StreamName, n: notifications.Notification
):
    await redis.xadd(stream_name, fields={"object": n.json()})
