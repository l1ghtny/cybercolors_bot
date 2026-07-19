import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api.models.bot_replies import ReplyEditModel
from api.routers.replies import (
    _group_reply_edits,
    _plan_trigger_sync,
    edit_replies,
)


def test_reply_edits_group_all_current_triggers_for_one_saved_reply():
    reply_id = uuid4()

    grouped = _group_reply_edits(
        [
            ReplyEditModel(
                id=reply_id,
                user_message="hello",
                bot_reply="Hi!",
            ),
            ReplyEditModel(
                id=reply_id,
                user_message="hey",
                bot_reply="Hi!",
            ),
        ]
    )

    assert grouped == {reply_id: ("Hi!", {"hello", "hey"})}


def test_reply_trigger_sync_deletes_removed_saved_trigger_and_adds_new_one():
    keep = SimpleNamespace(message="hello")
    remove = SimpleNamespace(message="old trigger")

    to_delete, to_create = _plan_trigger_sync(
        [keep, remove],
        {"hello", "new trigger"},
    )

    assert to_delete == [remove]
    assert to_create == {"new trigger"}


def test_reply_edits_reject_conflicting_responses_for_same_reply():
    reply_id = uuid4()

    with pytest.raises(ValueError):
        _group_reply_edits(
            [
                ReplyEditModel(
                    id=reply_id,
                    user_message="hello",
                    bot_reply="First response",
                ),
                ReplyEditModel(
                    id=reply_id,
                    user_message="hey",
                    bot_reply="Second response",
                ),
            ]
        )


def test_edit_replies_persists_trigger_removal_and_addition():
    reply_id = uuid4()
    saved_reply = SimpleNamespace(id=reply_id, server_id=123, bot_reply="Hi!")
    keep = SimpleNamespace(message="hello", reply_id=reply_id)
    remove = SimpleNamespace(message="old trigger", reply_id=reply_id)

    class Result:
        def __init__(self, *, first=None, all_items=None):
            self._first = first
            self._all = all_items or []

        def first(self):
            return self._first

        def all(self):
            return self._all

    class FakeSession:
        def __init__(self):
            self.exec_count = 0
            self.added = []
            self.deleted = []
            self.committed = False

        async def exec(self, _statement):
            self.exec_count += 1
            if self.exec_count == 1:
                return Result(first=saved_reply)
            return Result(all_items=[keep, remove])

        def add(self, item):
            self.added.append(item)

        async def delete(self, item):
            self.deleted.append(item)

        async def commit(self):
            self.committed = True

    session = FakeSession()
    result = asyncio.run(
        edit_replies(
            server_id=123,
            body=[
                ReplyEditModel(
                    id=reply_id,
                    user_message="hello",
                    bot_reply="Hi!",
                ),
                ReplyEditModel(
                    id=reply_id,
                    user_message="new trigger",
                    bot_reply="Hi!",
                ),
            ],
            session=session,
        )
    )

    assert session.deleted == [remove]
    assert [item.message for item in session.added] == ["new trigger"]
    assert session.committed is True
    assert result.created == 1
    assert result.deleted == 1
