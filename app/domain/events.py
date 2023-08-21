from __future__ import annotations

from typing import List

from app.bus import Event
from app.domain import entities, types
from app.domain.tickets import MatchingTicket


class UserDeactivated(Event):
    def __init__(self, user_id: types.UserID) -> None:
        super().__init__()
        self.user_id = user_id


class NewThreadCreated(Event):
    def __init__(
        self,
        thread: entities.Thread,
        tickets: List[MatchingTicket],
    ) -> None:
        super().__init__()
        self.thread = thread
        self.tickets = tickets


class MemberJoined(Event):
    def __init__(
        self,
        member_id: types.UserID,
        thread_id: types.ThreadID,
    ) -> None:
        super().__init__()
        self.mid = member_id
        self.tid = thread_id


class MemberLeaved(Event):
    def __init__(
        self,
        user_id: types.UserID,
        thread_id: types.ThreadID,
    ) -> None:
        super().__init__()
        self.user_id = user_id
        self.thread_id = thread_id
        self.sys_msg = entities.MemberLeavedMessage(who=self.user_id)


class ThreadClosed(Event):
    def __init__(
        self, thread_id: types.ThreadID, eot: entities.EndofThreadMessage
    ) -> None:
        super().__init__()
        self.thread_id = thread_id
        self.eot = eot


class MessageAdded(Event):
    def __init__(
        self,
        thread_id: types.ThreadID,
        msg: entities.AbstractMessage,
    ) -> None:
        super().__init__()
        self.thread_id = thread_id
        self.msg = msg
