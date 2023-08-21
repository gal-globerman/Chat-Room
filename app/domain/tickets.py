from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.types import ThreadID, TicketID, UserID


def create_ticket_id() -> TicketID:
    return uuid4().hex


class MatchingTicket(BaseModel):
    id: TicketID = Field(default_factory=create_ticket_id, frozen=True)
    user_id: UserID = Field(frozen=True)
    thread_id: ThreadID | Literal["None"] = "None"

    @property
    def key(self) -> str:
        return f"user:{self.user_id}:ticket:{self.id}"

    def __hash__(self) -> int:
        return hash(self.key)

    @property
    def matched_thread(self) -> ThreadID | None:
        if self.thread_id == "None":
            return None
        return self.thread_id
