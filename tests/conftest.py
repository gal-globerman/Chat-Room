import asyncio
import contextlib
import gc
import socket
from collections import namedtuple
from datetime import UTC, datetime
from functools import cache
from typing import Any, AsyncGenerator, Generator, List, Tuple
from unittest.mock import patch

import asyncpg
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import PostgresDsn, RedisDsn, SecretStr
from redis.asyncio import ConnectionPool, Redis
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from tortoise import Tortoise
from uvicorn.config import Config
from websockets.client import WebSocketClientProtocol, connect

from app import repos, services, settings
from app.bus import EventBus
from app.domain import entities, events
from app.infra.matchers import RandomMatcher
from app.lifespan import AppLifespanResource, load_resource
from app.main import app as _app
from app.services import handlers
from app.tasks import TaskExecutor

RSAKeyPair = namedtuple("RSAKeyPair", ["private_key", "public_key"])


@pytest.fixture
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    gc.collect()
    loop.close()


@pytest.fixture(scope="session")
def rsa_key_pair() -> Tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_key = private_key.public_key()
    return RSAKeyPair(
        public_key=SecretStr(
            pub_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode()
        ),
        private_key=SecretStr(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ).decode()
        ),
    )


@pytest.fixture(scope="session")
def db_container_port() -> Generator[str, Any, None]:
    with PostgresContainer() as postgres:
        yield postgres.get_exposed_port(5432)


@pytest.fixture
async def db_url(db_container_port: str) -> AsyncGenerator[str, None]:
    db_url = f"postgres://test:test@localhost:{db_container_port}/test"
    await Tortoise.init(db_url=db_url, modules={"models": ["db.models"]})
    await Tortoise.generate_schemas()
    await Tortoise.close_connections()

    yield db_url
    conn: asyncpg.Connection = await asyncpg.connect(
        f"postgres://test:test@localhost:{db_container_port}/template1"
    )
    await conn.fetch(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1 AND state = 'idle'",
        "test",
    )
    await conn.execute("""DROP DATABASE test""")
    await conn.execute("""CREATE DATABASE test""")
    await conn.close()


@pytest.fixture
async def db_pool(db_url: str):
    async with asyncpg.create_pool(db_url) as pool:
        yield pool


@pytest.fixture
async def db_conn(db_url: str) -> AsyncGenerator[asyncpg.Connection, Any]:
    conn: asyncpg.Connection = await asyncpg.connect(db_url)
    yield conn
    await conn.close()


@pytest.fixture(scope="session")
def redis_container_port() -> Generator[str, Any, None]:
    with RedisContainer() as redis:
        yield redis.get_exposed_port(6379)


@pytest.fixture
async def redis_url(redis_container_port: str):
    redis_url = f"redis://localhost:{redis_container_port}?decode_responses=True"
    r = Redis.from_url(redis_url)
    assert await r.ping()
    await r.config_set("notify-keyspace-events", "KEA")
    yield redis_url
    await r.flushall()
    await r.aclose()  # type: ignore


@pytest.fixture
async def redis_pool(redis_url: str):
    pool = ConnectionPool.from_url(redis_url)
    yield pool
    await pool.aclose()  # type: ignore


@pytest.fixture
async def redis_conn(
    redis_pool: ConnectionPool,
) -> AsyncGenerator[Redis, Any]:
    r = Redis.from_pool(redis_pool)  # type: ignore
    yield r


@pytest.fixture
def app_setting(db_url: str, redis_url: str, rsa_key_pair: RSAKeyPair):
    return settings.AppSettings(
        DATABASE_DSN=PostgresDsn(db_url),
        REDIS_DSN=RedisDsn(redis_url),
        PUBLIC_KEY=rsa_key_pair.public_key,
        PRIVATE_KEY=rsa_key_pair.private_key,
    )


@pytest.fixture
async def mock_app(
    app_setting: settings.AppSettings,
) -> AsyncGenerator[FastAPI, Any]:
    @cache
    def mock_load_resource():
        return AppLifespanResource(settings=app_setting)

    _app.dependency_overrides[load_resource] = mock_load_resource
    with patch("app.lifespan.load_resource", mock_load_resource):
        async with LifespanManager(_app) as manager:
            yield manager.app  # type: ignore
    mock_load_resource.cache_clear()
    _app.dependency_overrides = {}


@pytest.fixture
async def mock_app_without_lifespan(
    app_setting: settings.AppSettings,
) -> AsyncGenerator[FastAPI, Any]:
    @cache
    def mock_load_resource():
        return AppLifespanResource(settings=app_setting)

    _app.dependency_overrides[load_resource] = mock_load_resource
    with patch("app.lifespan.load_resource", mock_load_resource):
        yield _app
    mock_load_resource.cache_clear()
    _app.dependency_overrides = {}


@pytest.fixture
async def alice() -> entities.User:
    return entities.User(id="alice")


@pytest.fixture
async def alice_in_db(
    alice: entities.User, db_conn: asyncpg.Connection
) -> entities.User:
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        alice.id,
        alice.secret.get_secret_value(),
        datetime.now(UTC),
    )
    return alice


@pytest.fixture
async def bob_in_db(db_conn: asyncpg.Connection) -> entities.User:
    bob = entities.User(id="bob")
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        bob.id,
        bob.secret.get_secret_value(),
        datetime.now(UTC),
    )
    return bob


@pytest.fixture
async def mallory_in_db(db_conn: asyncpg.Connection) -> entities.User:
    mallory = entities.User(id="mallory")
    await db_conn.execute(
        """INSERT INTO public.user(id, secret, created_at) VALUES($1, $2, $3)""",
        mallory.id,
        mallory.secret.get_secret_value(),
        datetime.now(UTC),
    )
    return mallory


@pytest.fixture
async def thread_of_alice_and_bob(
    alice_in_db: entities.User, bob_in_db: entities.User, db_conn: asyncpg.Connection
) -> entities.Thread:
    thread = entities.Thread()
    thread.join((alice_in_db.id))
    thread.join((bob_in_db.id))
    async with db_conn.transaction():
        await db_conn.execute(
            "INSERT INTO public.thread(id, created_at) VALUES($1, $2)",
            thread.id,
            datetime.now(UTC),
        )
        for user_id, _ in thread.members.items():
            await db_conn.execute(
                "INSERT INTO public.room(thread_id, user_id, created_at, active) VALUES($1, $2, $3, $4)",
                thread.id,
                user_id,
                datetime.now(UTC),
                True,
            )
    return thread


@pytest.fixture
async def client(mock_app: FastAPI) -> AsyncGenerator[AsyncClient, Any]:
    async with AsyncClient(app=mock_app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_repo(db_conn: asyncpg.Connection):
    return repos.UserRepository(db_conn)


@pytest.fixture
def room_repo(db_conn: asyncpg.Connection):
    return repos.RoomRepository(db_conn)


@pytest.fixture
async def alice_client(
    mock_app: FastAPI,
    user_repo: repos.UserRepository,
    app_setting: settings.AppSettings,
    alice_in_db: entities.User,
) -> AsyncGenerator[AsyncClient, Any]:
    jwt_token = await services.authenticate_user(
        alice_in_db.secret.get_secret_value(), user_repo, app_setting.PRIVATE_KEY
    )
    async with AsyncClient(
        app=mock_app,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_token}"},
    ) as ac:
        yield ac


@pytest.fixture
async def bob_client(
    mock_app: FastAPI,
    user_repo: repos.UserRepository,
    app_setting: settings.AppSettings,
    bob_in_db: entities.User,
) -> AsyncGenerator[AsyncClient, Any]:
    jwt_token = await services.authenticate_user(
        bob_in_db.secret.get_secret_value(), user_repo, app_setting.PRIVATE_KEY
    )
    async with AsyncClient(
        app=mock_app,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_token}"},
    ) as ac:
        yield ac


@pytest.fixture
async def mallory_client(
    mock_app: FastAPI,
    user_repo: repos.UserRepository,
    app_setting: settings.AppSettings,
    mallory_in_db: entities.User,
) -> AsyncGenerator[AsyncClient, Any]:
    jwt_token = await services.authenticate_user(
        mallory_in_db.secret.get_secret_value(), user_repo, app_setting.PRIVATE_KEY
    )
    async with AsyncClient(
        app=mock_app,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_token}"},
    ) as ac:
        yield ac


class TestServer(uvicorn.Server):
    def __init__(self, config: Config) -> None:
        super().__init__(config)
        self.started_event = asyncio.Event()

    async def startup(self, sockets: List[socket.socket] | None = None):
        await super().startup(sockets)
        self.started_event.set()


@pytest.fixture
async def run_app(mock_app_without_lifespan: FastAPI) -> AsyncGenerator[str, Any]:
    config = uvicorn.Config(mock_app_without_lifespan, lifespan="on")
    server = TestServer(config)
    task = asyncio.create_task(server.serve())
    await server.started_event.wait()
    yield f"ws://{config.host}:{config.port}"
    server.should_exit = True
    await server.shutdown()
    await task


class AsyncWSClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.jwt_token = token
        self.base_url = base_url

    @contextlib.asynccontextmanager
    async def connect(self, path: str) -> AsyncGenerator[WebSocketClientProtocol, Any]:
        async with connect(
            f"{self.base_url}{path}",
            extra_headers={"Authorization": f"Bearer {self.jwt_token}"},
        ) as ws:
            yield ws


@pytest.fixture
async def alice_ws_client(
    run_app: str,
    db_conn: asyncpg.Connection,
    app_setting: settings.AppSettings,
    alice_in_db: entities.User,
):
    repo = repos.UserRepository(db_conn)
    jwt_token = await services.authenticate_user(
        alice_in_db.secret.get_secret_value(), repo, app_setting.PRIVATE_KEY
    )
    yield AsyncWSClient(run_app, jwt_token)


@pytest.fixture
async def mallory_ws_client(
    run_app: str,
    db_conn: asyncpg.Connection,
    app_setting: settings.AppSettings,
    mallory_in_db: entities.User,
):
    repo = repos.UserRepository(db_conn)
    jwt_token = await services.authenticate_user(
        mallory_in_db.secret.get_secret_value(), repo, app_setting.PRIVATE_KEY
    )
    yield AsyncWSClient(run_app, jwt_token)


@pytest.fixture
async def bus(db_url: str, redis_conn: Redis):
    async with asyncpg.create_pool(db_url) as pool:
        bus = EventBus()
        bus.handlers = {
            events.NewThreadCreated: [
                handlers.CreateThread(pool),
                handlers.SetTicketResultHandler(redis_conn),
                handlers.NotifyThreadJoined(redis_conn),
            ],
            events.MemberLeaved: [
                handlers.RemoveMember(pool),
                handlers.ClearTicket(redis_conn),
                handlers.NotifyMemberRemoved(redis_conn),
            ],
            events.ThreadClosed: [handlers.ArchiveThread(redis_conn)],
            events.MessageAdded: [handlers.MessageAddedHandler(redis_conn)],
        }
        yield bus


@pytest.fixture
async def bg_task(bus: EventBus, redis_conn: Redis):
    async with TaskExecutor(bus), TaskExecutor(RandomMatcher(redis_conn)):
        yield
