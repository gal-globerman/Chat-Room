from enum import StrEnum, auto, unique
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


@unique
class _NotificationCodes(StrEnum):
    THREAD_JOINED = auto()
    THREAD_LEAVED = auto()


class Notification(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: Optional[float] = None
    code: _NotificationCodes
    details: dict = Field(default_factory=dict)

    def json(self) -> str:  # type: ignore
        return super().model_dump_json(exclude_none=True)


class ThreadJoinedNotification(Notification):
    code: _NotificationCodes = _NotificationCodes.THREAD_JOINED


class ThreadLeavedNotification(Notification):
    code: _NotificationCodes = _NotificationCodes.THREAD_LEAVED
