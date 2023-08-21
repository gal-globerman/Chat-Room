from tortoise.fields import (
    BooleanField,
    CharField,
    DatetimeField,
    ForeignKeyField,
    ForeignKeyRelation,
    ReverseRelation,
)
from tortoise.models import Model


class User(Model):
    id = CharField(pk=True, max_length=32)
    secret = CharField(unique=True, index=True, max_length=32)
    created_at = DatetimeField()
    active = BooleanField(default=True)
    rooms: ReverseRelation["Room"]

    class Meta:
        table = "user"


class Thread(Model):
    id = CharField(pk=True, max_length=32)
    created_at = DatetimeField()
    rooms: ReverseRelation["Room"]

    class Meta:
        table = "thread"


class Room(Model):
    user: ForeignKeyRelation[User] = ForeignKeyField(
        "models.User", related_name="rooms"
    )
    thread: ForeignKeyRelation[Thread] = ForeignKeyField(
        "models.Thread", related_name="rooms"
    )
    created_at = DatetimeField()
    active = BooleanField()

    class Meta:
        table = "room"
        unique_together = (("user", "thread"),)
        indexes = (("user",), ("thread",))
