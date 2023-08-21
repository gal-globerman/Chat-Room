import logging
from typing import Annotated, AsyncGenerator, Optional

import jwt
from asyncpg import Pool
from fastapi import Depends, Header, WebSocket, status
from fastapi.exceptions import HTTPException, WebSocketException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from redis.asyncio import ConnectionPool, Redis

from app import repos, services
from app.domain import entities, types
from app.lifespan import AppLifespanResource, load_resource
from app.settings import AppSettings

WS_3003_FORBIDDEN = 3003


class WSBearer(HTTPBearer):
    async def __call__(  # type: ignore
        self,
        websocket: WebSocket,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Optional[HTTPAuthorizationCredentials]:
        await websocket.accept()
        scheme, credentials = get_authorization_scheme_param(authorization)
        if not (authorization and scheme and credentials):
            if self.auto_error:
                raise WebSocketException(
                    code=WS_3003_FORBIDDEN, reason="Not authenticated"
                )
            else:
                return None
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise WebSocketException(
                    code=3003, reason="Invalid authentication credentials"
                )
            else:
                return None
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)


auth_scheme = HTTPBearer()
ws_auth_scheme = WSBearer()


AppLifespanResourceDep = Annotated[AppLifespanResource, Depends(load_resource)]


async def get_user_id(
    cred: Annotated[HTTPAuthorizationCredentials, Depends(auth_scheme)],
    resource: AppLifespanResourceDep,
) -> types.UserID:
    try:
        return services.is_token_valid(cred.credentials, resource.settings.PUBLIC_KEY)
    except services.exceptions.TokenExpired as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from e
    except Exception as e:
        logging.exception(e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR) from e


async def get_ws_user_id(
    cred: Annotated[HTTPAuthorizationCredentials, Depends(ws_auth_scheme)],
    resource: AppLifespanResourceDep,
) -> types.UserID:
    try:
        return services.is_token_valid(cred.credentials, resource.settings.PUBLIC_KEY)
    except (services.exceptions.TokenExpired, jwt.InvalidTokenError) as e:
        raise WebSocketException(code=3003) from e
    except Exception as e:
        raise WebSocketException(code=status.WS_1011_INTERNAL_ERROR) from e


async def load_settings(resource: AppLifespanResourceDep) -> AppSettings:
    return resource.settings


AppSettingsDep = Annotated[AppSettings, Depends(load_settings)]


async def get_db_pool(
    resource: AppLifespanResourceDep,
) -> Pool:
    return resource.db_pool


DBConnectionPoolDep = Annotated[Pool, Depends(get_db_pool)]


async def get_redis_connection_pool(
    resource: AppLifespanResourceDep,
) -> ConnectionPool:
    return resource.redis_pool


RedisConnectionPoolDep = Annotated[ConnectionPool, Depends(get_redis_connection_pool)]


async def get_redis_connection(
    redis_pool: RedisConnectionPoolDep,
) -> Redis:
    return Redis.from_pool(redis_pool)  # type: ignore


RedisConnectionDep = Annotated[Redis, Depends(get_redis_connection)]


async def create_user_repository(
    pool: DBConnectionPoolDep,
) -> AsyncGenerator[repos.UserRepository, None]:
    async with pool.acquire() as conn:
        yield repos.UserRepository(conn)


UserRepositoryDep = Annotated[repos.UserRepository, Depends(create_user_repository)]


async def create_thread_repository(
    pool: DBConnectionPoolDep,
) -> AsyncGenerator[repos.ThreadRepository, None]:
    async with pool.acquire() as conn:
        yield repos.ThreadRepository(conn)


ThreadRepositoryDep = Annotated[
    repos.ThreadRepository, Depends(create_thread_repository)
]


async def create_room_repository(
    pool: DBConnectionPoolDep,
) -> AsyncGenerator[repos.RoomRepository, None]:
    async with pool.acquire() as conn:
        yield repos.RoomRepository(conn)


RoomRepositoryDep = Annotated[repos.RoomRepository, Depends(create_room_repository)]


async def create_ticket_repository(
    redis: RedisConnectionDep,
) -> repos.TicketRepository:
    return repos.TicketRepository(redis)


TicketRepositoryDep = Annotated[
    repos.TicketRepository, Depends(create_ticket_repository)
]


async def get_user(
    user_id: Annotated[types.UserID, Depends(get_user_id)],
    user_repo: UserRepositoryDep,
) -> entities.User:
    try:
        user = await user_repo.get(user_id)
    except (Exception, repos.exceptions.RepositoryError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR) from e
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


async def get_ws_user(
    user_id: Annotated[types.UserID, Depends(get_ws_user_id)],
    user_repo: UserRepositoryDep,
) -> entities.User:
    try:
        user = await user_repo.get(user_id)
    except (Exception, repos.exceptions.RepositoryError) as e:
        raise WebSocketException(code=status.WS_1011_INTERNAL_ERROR) from e
    if user is None:
        raise WebSocketException(code=3000)
    return user


UserDep = Annotated[entities.User, Depends(get_user)]
WSUserDep = Annotated[entities.User, Depends(get_ws_user)]
