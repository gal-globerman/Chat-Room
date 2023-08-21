from __future__ import annotations

import abc
import json
from datetime import datetime
from typing import ClassVar, Dict, Generic, List, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_serializer

from app.domain import events, exceptions, tickets, types


def create_id() -> types.UserID:
    return uuid4().hex


def create_secret() -> types.UserSecret:
    return types.UserSecret(uuid4().hex)


class Entity(BaseModel):
    _events: List[events.Event] = PrivateAttr(default_factory=list)


class User(Entity):
    SYSTEM_USER_ID: ClassVar = "system"
    model_config = ConfigDict(validate_assignment=True)

    id: types.UserID = Field(frozen=True, default_factory=create_id)
    secret: types.UserSecret = Field(frozen=True, default_factory=create_secret)
    active: bool = True

    async def deactivate(self) -> None:
        self.active = False
        event = events.UserDeactivated(self.id)
        self._events.append(event)
        await event.emit()


ContentType = TypeVar("ContentType")


class AbstractMessage(Entity, Generic[ContentType]):
    model_config = ConfigDict(
        frozen=True,
    )

    id: types.MessageID = Field(default_factory=create_id)
    user_id: types.UserID
    thread_id: Optional[types.ThreadID] = None
    time: Optional[datetime] = None
    content: ContentType

    @field_serializer("time")
    def serialize_dt(self, time: datetime, _info):
        return time.timestamp()

    @property
    def timestamp(self) -> float:
        if self.time is None:
            raise ValueError("self.time is None")
        return self.time.timestamp()

    @abc.abstractmethod
    def __str__(self) -> str:
        pass


class Text(AbstractMessage[str]):
    EOT: ClassVar = "EOT"
    MEMBER_LEAVE: ClassVar = "MEMBER_LEAVE"

    def __str__(self) -> str:
        return self.content


class EndofThreadMessage(Text):
    content: str = json.dumps({"flag": Text.EOT})
    user_id: types.UserID = "system"

    def __init__(self):
        super().__init__()  # type: ignore


class MemberLeavedMessage(Text):
    user_id: types.UserID = "system"

    def __init__(self, who: types.UserID):
        super().__init__(content=json.dumps({"flag": Text.MEMBER_LEAVE, "who": who}))  # type: ignore


class Member(BaseModel):
    id: types.UserID


class Thread(Entity):
    model_config = ConfigDict(validate_assignment=True)

    id: types.ThreadID = Field(frozen=True, default_factory=create_id)
    members: Dict[types.UserID, Member] = {}

    @classmethod
    async def from_pair(
        cls, ticket1: tickets.MatchingTicket, ticket2: tickets.MatchingTicket
    ) -> "Thread":
        thread = cls()
        ticket1.thread_id = thread.id
        ticket2.thread_id = thread.id
        thread.join(ticket1.user_id)
        thread.join(ticket2.user_id)

        event = events.NewThreadCreated(thread, [ticket1, ticket2])
        thread._events.append(event)
        await event.emit()

        return thread

    @property
    def active(self) -> bool:
        return len(self.members) == 2

    def has_member(self, member_id: types.UserID) -> bool:
        return member_id in self.members

    def join(self, user_id: types.UserID):
        if len(self.members) == 2:
            raise exceptions.NumOfMemberHasReachedTheLimit
        if self.has_member(user_id):
            raise exceptions.MemberAlreadyJoined

        self.members[user_id] = Member(id=user_id)
        event = events.MemberJoined(user_id, self.id)
        self._events.append(event)

    async def leave(self, user_id: types.UserID):
        if not self.has_member(user_id):
            raise exceptions.MemberNotInThread

        for user_id in self.members.keys():
            event = events.MemberLeaved(user_id, self.id)
            self._events.append(event)
            await event.emit(eager=True)
        self.members.clear()
        await events.ThreadClosed(self.id, EndofThreadMessage()).emit(eager=False)

    async def add_message(self, msg: AbstractMessage):
        if not self.has_member(msg.user_id):
            raise exceptions.MemberNotInThread
        event = events.MessageAdded(self.id, msg)
        self._events.append(event)
        await event.emit(eager=False)
