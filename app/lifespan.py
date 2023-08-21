from contextlib import asynccontextmanager
from functools import cache, cached_property
from typing import Optional

import asyncpg
from fastapi import FastAPI
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.bus import EventBus
from app.domain import events
from app.infra.matchers import RandomMatcher
from app.services import handlers
from app.settings import AppSettings
from app.tasks import TaskExecutor


class AppLifespanResource:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = AppSettings() if settings is None else settings  # type: ignore

    @cached_property
    def redis_pool(self) -> ConnectionPool:
        return ConnectionPool.from_url(self.settings.REDIS_URL)

    def create_redis(self) -> Redis:
        return Redis.from_pool(self.redis_pool)  # type: ignore

    @asynccontextmanager
    async def __call__(self):
        async with (
            asyncpg.create_pool(dsn=self.settings.DATABASE_URL) as pool,
            TaskExecutor(self.prepare_event_bus(pool)),
            TaskExecutor(RandomMatcher(self.create_redis())),
        ):
            self.db_pool = pool
            yield
        await self.redis_pool.aclose()  # type: ignore

    def prepare_event_bus(self, pool: asyncpg.Pool) -> EventBus:
        bus = EventBus()
        bus.handlers = {
            events.NewThreadCreated: [
                handlers.CreateThread(pool),
                handlers.SetTicketResultHandler(self.create_redis()),
                handlers.NotifyThreadJoined(self.create_redis()),
            ],
            events.MemberLeaved: [
                handlers.RemoveMember(pool),
                handlers.ClearTicket(self.create_redis()),
                handlers.NotifyMemberRemoved(self.create_redis()),
            ],
            events.ThreadClosed: [handlers.ArchiveThread(self.create_redis())],
            events.MessageAdded: [handlers.MessageAddedHandler(self.create_redis())],
        }
        return bus


@cache
def load_resource():
    return AppLifespanResource()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_reource = load_resource()
    async with app_reource():
        yield
