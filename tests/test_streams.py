import asyncio
import time

from redis.asyncio import Redis

from app.infra import streams


async def test_fetch_before_time(redis_conn: Redis):
    def decoder(stream_name: str, time: float, data: dict) -> str:
        return data["data"]

    ids = []
    for i in range(3):
        ids.append(await redis_conn.xadd("t", fields={"data": f"{i}"}))
        await asyncio.sleep(0.001)

    stream = streams.Stream(redis_conn)
    time = int(ids[1].split("-")[0])

    ans = [
        text async for text in stream.fetch_before("t", time, count=1, decoder=decoder)
    ]
    assert len(ans) == 1
    assert ans[0] == "1"


async def test_fetch_before_time_but_empty(redis_conn: Redis):
    def decoder(stream_name: str, time: float, data: dict) -> str:
        return data["data"]

    stream = streams.Stream(redis_conn)
    assert (
        len(
            [
                text
                async for text in stream.fetch_before(
                    "t", int(time.time() * 1000), count=10, decoder=decoder
                )
            ]
        )
        == 0
    )


async def test_listen_multiple_stream_message_after_a_certain_timestamp_offset(
    redis_conn: Redis,
):
    def decoder(stream_name: str, time: float, data: dict) -> str:
        return data["data"]

    offset = await redis_conn.xadd("t0", fields={"data": "old"})
    await redis_conn.xadd("t0", fields={"data": "new"})
    stream = streams.Stream(redis_conn)
    stream.set_offsets({"t0": offset})
    assert [text async for text in stream.listen(decoder=decoder)] == ["new"]


async def test_listen_multiple_stream_message_keep_updating_offset(redis_conn: Redis):
    def decoder(stream: str, time: float, data: dict) -> str:
        return data["data"]

    stream = streams.Stream(redis_conn)
    stream.set_offsets({"t0": 0})
    res = []
    await redis_conn.xadd("t0", fields={"data": "old"})
    async for text in stream.listen(decoder=decoder):
        res.append(text)
    await redis_conn.xadd("t0", fields={"data": "new"})
    async for text in stream.listen(decoder=decoder):
        res.append(text)

    assert res == ["old", "new"]
