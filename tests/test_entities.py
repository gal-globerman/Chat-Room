from datetime import datetime, timezone

import pytest

from app.domain import entities, events, exceptions, tickets


def test_user():
    user = entities.User()
    assert user.active


async def test_user_deactivate():
    user = entities.User()
    user._events.clear()
    await user.deactivate()
    assert not user.active
    assert len(user._events) == 1
    assert isinstance(user._events[0], events.UserDeactivated)


def test_create_text_entity():
    entities.Text(user_id="", content="")


def test_text_entity__str__():
    assert str(entities.Text(user_id="", content="")) == ""


def test_text_isinstance():
    text = entities.Text(content="", user_id="")
    assert isinstance(text, entities.AbstractMessage)


def test_text_serialize():
    time = datetime.now(timezone.utc)
    text = entities.Text(user_id="alice", content="Hi", time=time)
    res = text.model_dump(exclude_none=True)
    assert "thread_id" not in res
    assert res["time"] == time.timestamp()


async def test_create_thread_from_ticket():
    ticket1 = tickets.MatchingTicket(user_id="alice")
    ticket2 = tickets.MatchingTicket(user_id="bob")

    thread = await entities.Thread.from_pair(ticket1, ticket2)
    assert len(thread._events) == 3


async def test_user_join_thread():
    user = entities.User()
    thread = entities.Thread()
    thread.join(user.id)
    assert len(thread.members) == 1


async def test_user_join_thread_but_alread_in():
    user = entities.User()
    thread = entities.Thread()
    thread.join(user.id)

    with pytest.raises(exceptions.MemberAlreadyJoined):
        thread.join(user.id)


async def test_user_join_but_reach_limit():
    user1 = entities.User()
    user2 = entities.User()
    thread = entities.Thread()
    thread.join(user1.id)
    thread.join(user2.id)

    user3 = entities.User()
    with pytest.raises(exceptions.NumOfMemberHasReachedTheLimit):
        thread.join(user3.id)


async def test_user_levea_thread():
    user1 = entities.User()
    user2 = entities.User()
    thread = entities.Thread()
    thread.join(user1.id)
    thread.join(user2.id)
    thread._events.clear()
    await thread.leave(user1.id)
    assert len(thread.members) == 0
    assert len(thread._events) == 2
    assert isinstance(thread._events[0], events.MemberLeaved)
    assert isinstance(thread._events[1], events.MemberLeaved)


async def test_add_message_to_thread():
    user = entities.User()
    thread = entities.Thread()
    thread.join(user.id)
    thread._events.clear()
    text = entities.Text(content="Hello world", user_id=user.id)

    await thread.add_message(text)

    assert isinstance(thread._events[0], events.MessageAdded)


async def test_add_message_to_thread_but_user_not_joined():
    user = entities.User()
    thread = entities.Thread()
    text = entities.Text(content="Hello world", user_id=user.id)
    with pytest.raises(exceptions.MemberNotInThread):
        await thread.add_message(text)
