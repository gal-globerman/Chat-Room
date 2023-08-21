import asyncio
import json
import logging
from datetime import datetime
from typing import Annotated, Any, AsyncIterator, Dict, List

import pydantic
import websockets
from fastapi import Body, Query, Response, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_serializer

from app import services
from app.api import depends
from app.infra import listeners, sets, streams
from app.infra.types import StreamName

logger = logging.getLogger()

router = APIRouter()


@router.get("/", include_in_schema=False)
async def home():
    return RedirectResponse(url="/docs")


class CreatedUser(BaseModel):
    secret: str


@router.post("/users", response_model=CreatedUser)
async def create_user(user_repo: depends.UserRepositoryDep):
    user_secret = await services.create_user(user_repo)
    return JSONResponse(
        jsonable_encoder(CreatedUser(secret=user_secret.get_secret_value())),
        status_code=status.HTTP_201_CREATED,
    )


class AuthPayload(BaseModel):
    secret: str


class Token(BaseModel):
    access_token: str
    token_type: str


@router.post("/tokens", response_model=Token)
async def login(
    payload: AuthPayload,
    settings: depends.AppSettingsDep,
    user_repo: depends.UserRepositoryDep,
):
    try:
        access_token = await services.authenticate_user(
            payload.secret, user_repo, settings.PRIVATE_KEY, exp=settings.JWT_LIFETIME
        )
        return JSONResponse(
            jsonable_encoder(
                Token(
                    access_token=access_token,
                    token_type="bearer",
                )
            ),
            status_code=status.HTTP_200_OK,
        )
    except services.AuthenticationFail as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="incorrect password"
        ) from e


class UserInfo(BaseModel):
    id: str


@router.get("/users/me", response_model=UserInfo)
async def get_user_info(user: depends.UserDep):
    return JSONResponse(jsonable_encoder(UserInfo(id=user.id)))


class MatchRequestReturnInfo(BaseModel):
    ticket_id: str


@router.post("/match", response_model=MatchRequestReturnInfo)
async def match_user(
    user: depends.UserDep,
    redis: depends.RedisConnectionDep,
    ticket_repo: depends.TicketRepositoryDep,
    room_repo: depends.RoomRepositoryDep,
):
    try:
        ticket = await services.user_matches(
            user.id, sets.RandomMatchingSet(redis), ticket_repo, room_repo
        )
        return JSONResponse(
            jsonable_encoder(MatchRequestReturnInfo(ticket_id=ticket.id))
        )
    except services.exceptions.MatchingPermissionDenied as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS) from e


class MatchingResult(BaseModel):
    thread_id: str


@router.get("/match/tickets/{ticket_id}")
async def wait_matching_result(
    ticket_id: str,
    user: depends.UserDep,
    ticket_repo: depends.TicketRepositoryDep,
    settings: depends.AppSettingsDep,
):
    try:
        listener = listeners.ValueListerner(settings.REDIS_URL)
        gen = await services.user_wait_matching_result(
            user.id, ticket_id, ticket_repo, listener
        )
        return StreamingResponse(gen, media_type="application/json")
    except services.ResourceNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from e


class MatchTicket(BaseModel):
    id: str
    thread_id: str | None


@router.get("/tickets")
async def get_all_tickets(
    user: depends.UserDep,
    ticket_repo: depends.TicketRepositoryDep,
):
    tickets = await services.user_get_tickets(user.id, ticket_repo)
    return JSONResponse(
        jsonable_encoder(
            [MatchTicket(id=t.id, thread_id=t.matched_thread) for t in tickets]
        )
    )


@router.delete("/tickets/{ticket_id}")
async def delete_ticket(
    ticket_id: str, user: depends.UserDep, ticket_repo: depends.TicketRepositoryDep
):
    try:
        await services.user_delete_ticket(user.id, ticket_id, ticket_repo)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except services.ResourceNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from e
    except services.PermissionDenied as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from e


class ThreadIDs(BaseModel):
    ids: List[str]


@router.get("/threads", response_model=ThreadIDs)
async def get_user_threads(user: depends.UserDep, room_repo: depends.RoomRepositoryDep):
    ids = await services.user_get_thread_ids(user, room_repo)
    return JSONResponse(jsonable_encoder(ThreadIDs(ids=ids)))  # type: ignore


@router.post("/threads/{thread_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_thread(
    thread_id: str, user: depends.UserDep, thread_repo: depends.ThreadRepositoryDep
):
    try:
        await services.user_leave_thread(user, thread_id, thread_repo)
        return Response(status_code=status.HTTP_200_OK)
    except (
        services.exceptions.PermissionDenied,
        services.exceptions.ResourceNotFound,
    ) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from e


class OutgoingMessage(BaseModel):
    id: str
    uid: str
    tid: str
    text: str
    time: float


class ThreadMessages(BaseModel):
    data: List[OutgoingMessage]


@router.get("/threads/{thread_id}")
async def get_old_messages(
    thread_id: str,
    user: depends.UserDep,
    room_repo: depends.RoomRepositoryDep,
    redis: depends.RedisConnectionDep,
    t: Annotated[datetime, Query()],
    count: Annotated[int, Query(gt=0, le=30)] = 30,  # TODO:Refactor
):
    try:
        timestamp = int(t.timestamp() * 1000)
        stream = streams.Stream(redis)
        messages = await services.user_get_old_messages(
            user, thread_id, timestamp, count, stream, room_repo
        )
        data = []
        for m in messages:
            data.append(
                OutgoingMessage(
                    id=m.id, text=m.content, tid=m.id, time=m.timestamp, uid=m.user_id
                )
            )
        return JSONResponse(jsonable_encoder(ThreadMessages(data=data)))
    except services.exceptions.PermissionDenied as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from e


Offset = Annotated[datetime, Field()]


class MesseageListenOffset(RootModel):
    model_config = ConfigDict(frozen=True)
    root: dict[StreamName, Offset]

    def stream_names(self) -> List[StreamName]:
        return list(self.root.keys())

    @model_serializer
    def ser_model(self) -> Dict[str, Any]:
        return {k: int(v.timestamp() * 1000) for k, v in self.root.items()}


class FastAPIWebSocketHeartbeatChecker(services.AbstractWebSocketHeartbeatChecker):
    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket

    async def check_keep_going(self) -> bool:
        await self.ws.send_text("PING")
        try:
            heartbeat = await asyncio.wait_for(self.ws.receive_text(), timeout=1)
        except TimeoutError:
            return False
        return heartbeat == "PONG"


@router.websocket("/messages/down")
async def delivery_messages(
    websocket: WebSocket,
    user: depends.WSUserDep,
    redis: depends.RedisConnectionDep,
    room_repo: depends.RoomRepositoryDep,
):
    try:
        raw_query = await websocket.receive_json()
        query = MesseageListenOffset.model_validate(raw_query)
        offsets = query.model_dump()
        listener = streams.Stream(redis)
        listener.set_offsets(offsets)
        checker = FastAPIWebSocketHeartbeatChecker(websocket)

        async for message in services.user_listen_messages(
            checker, user, listener, room_repo
        ):
            await websocket.send_json(
                OutgoingMessage(
                    text=message.content,
                    id=message.id,
                    tid=message.thread_id,  # type: ignore
                    uid=message.user_id,
                    time=message.timestamp,
                ).model_dump()
            )
        await websocket.close(status.WS_1000_NORMAL_CLOSURE)
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosedOK):
        pass
    except services.exceptions.PermissionDenied:
        await websocket.close(depends.WS_3003_FORBIDDEN)
    except (json.JSONDecodeError, pydantic.ValidationError):
        await websocket.close(status.WS_1003_UNSUPPORTED_DATA)
    except Exception as e:
        logger.exception(e)
        await websocket.close(status.WS_1011_INTERNAL_ERROR)


class IncomingMessage(BaseModel):
    text: str
    tid: str


@router.websocket("/messages/up")
async def processs_incoming_messages(
    websocket: WebSocket,
    user: depends.WSUserDep,
    pool: depends.DBConnectionPoolDep,
):
    try:
        async for data in websocket.iter_json():
            inconming_message = IncomingMessage(**data)
            await services.user_send_message(
                user, inconming_message.text, inconming_message.tid, pool
            )
    except (json.JSONDecodeError, pydantic.ValidationError):
        await websocket.close(status.WS_1003_UNSUPPORTED_DATA)
    except Exception as e:
        logger.exception(e)
        await websocket.close(status.WS_1011_INTERNAL_ERROR)


@router.get("/users/me/notifications")
async def listen_notification(
    user: depends.UserDep,
    redis: depends.RedisConnectionDep,
    t: Annotated[datetime, Query()],
):
    offset = int(t.timestamp() * 1000)
    listener = streams.Stream(redis)
    listener.set_offsets({str(user.id): offset})

    async def to_str_generator(g: AsyncIterator[BaseModel]):
        async for n in g:
            yield n.model_dump_json()

    return StreamingResponse(
        to_str_generator(services.user_listen_notification(listener)),
        media_type="application/json",
    )


class ReadOffset(BaseModel):
    offset: float


@router.get("/users/me/notifications/read-offset", response_model=ReadOffset)
async def get_notification_read_offset(
    user: depends.UserDep, redis: depends.RedisConnectionDep
):
    mtimestamp = await services.user_get_current_read_notification_offset(user, redis)
    return JSONResponse(jsonable_encoder(ReadOffset(offset=mtimestamp / 1000)))


@router.patch("/users/me/notifications/read-offset")
async def update_notification_read_offset(
    new_offset: Annotated[int, Body(embed=True)],
    user: depends.UserDep,
    redis: depends.RedisConnectionDep,
):
    try:
        await services.user_update_last_read_notification_offset(
            user, redis, new_offset
        )
    except services.PermissionDenied as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
