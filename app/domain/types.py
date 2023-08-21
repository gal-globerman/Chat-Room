from typing import TypeAlias

from pydantic import SecretStr

UserID: TypeAlias = str
TicketID: TypeAlias = str
MessageID: TypeAlias = str
ThreadID: TypeAlias = str
UserSecret = SecretStr
