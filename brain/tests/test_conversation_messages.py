"""The conversation on the wire: earlier turns as messages, the partner's own lines as its own,
the cache breakpoints where they pay, and LIVE with their words as the only new message."""

import sqlite3
from collections.abc import Iterator

import pytest

from brain.director.talker import reply
from brain.llm.base import OPENING_LINE, ChatTurn, SystemPart, merged_turns
from brain.llm.claude_tools import chat_messages, history_messages
from brain.memory.context import LIVE_END, LIVE_HEADER, MEMORY_HEADER
from brain.memory.db import connect
from brain.memory.gather import gather_context
from brain.memory.layers import build_context
from brain.tests.fake_gemini import gemini, model_turn
from brain.tests.test_llm_caching import TOOLS, FakeMessages, claude
from brain.tests.test_memory_context_turns import (
    COMPLAINT,
    GAME,
    LIVE,
    SECOND_ASK,
    play_the_repeated_question,
)

CACHED = {"type": "ephemeral"}


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def text_of(message: dict[str, object]) -> str:
    content = message["content"]
    if isinstance(content, str):
        return content
    assert isinstance(content, list)
    return "\n".join(block["text"] for block in content)


async def test_the_repeated_question_reaches_the_model_as_its_own_line(
    conn: sqlite3.Connection,
) -> None:
    session = play_the_repeated_question(conn)
    inputs = gather_context(conn, GAME, session, LIVE, query=COMPLAINT, current=COMPLAINT)
    context = build_context(inputs)
    messages = FakeMessages(["Sorry, ", "I did."])
    await reply(claude(messages), COMPLAINT, "supportive", 30, context, "Warm.")

    sent = messages.kwargs
    rules, memory = sent["system"]
    assert rules["cache_control"] == CACHED and memory["cache_control"] == CACHED
    assert memory["text"].startswith(MEMORY_HEADER) and "playstyle 0" in memory["text"]

    *history, latest = sent["messages"]
    # The partner opened, so a user line comes first, as the API needs.
    assert [m["role"] for m in history] == ["user", "assistant"] * 3
    assert text_of(history[0]) == OPENING_LINE
    assert history[-1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": SECOND_ASK, "cache_control": CACHED}],
    }
    # Their words come once, after LIVE, in the only message that isn't cached.
    assert latest["role"] == "user"
    assert latest["content"].startswith(LIVE_HEADER)
    assert latest["content"].endswith(f"{LIVE_END}\n\n{COMPLAINT}")
    assert sum(COMPLAINT in text_of(m) for m in sent["messages"]) == 1


def test_turns_from_one_side_merge_and_a_user_line_goes_first() -> None:
    turns = [
        ChatTurn("assistant", "Hey."),
        ChatTurn("assistant", "Ready?"),
        ChatTurn("user", " "),
        ChatTurn("user", "yes"),
        ChatTurn("user", "go"),
    ]
    assert merged_turns(turns) == [
        ChatTurn("user", OPENING_LINE),
        ChatTurn("assistant", "Hey.\nReady?"),
        ChatTurn("user", "yes\ngo"),
    ]
    assert merged_turns([]) == []


def test_only_the_last_earlier_turn_carries_the_breakpoint() -> None:
    messages = history_messages([ChatTurn("user", "hi"), ChatTurn("assistant", "Hey.")])
    assert messages[0]["content"] == [{"type": "text", "text": "hi"}]
    assert messages[1]["content"][-1]["cache_control"] == CACHED
    assert history_messages([]) == []


def test_a_line_nobody_answered_joins_their_latest_message() -> None:
    # Such as a bare "okay" the partner let be: the APIs want turns to alternate.
    messages = chat_messages([ChatTurn("assistant", "Done."), ChatTurn("user", "okay")], "now?")
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"] == [
        {"type": "text", "text": "okay", "cache_control": CACHED},
        {"type": "text", "text": "now?"},
    ]
    assert chat_messages([], "hi") == [{"role": "user", "content": "hi"}]


async def test_a_tool_turn_starts_from_the_conversation() -> None:
    messages = FakeMessages(text="Sure.")
    history = (ChatTurn("user", "hi"), ChatTurn("assistant", "Want to build?"))
    parts = (SystemPart("Rules.", cache=True), SystemPart("MEMORY", cache=True))
    chat = claude(messages).tool_chat(parts, TOOLS, 100, history)
    step = await chat.send("LIVE\n\nyes")
    assert step.text == "Sure."
    sent = messages.kwargs["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant"]
    assert sent[1]["content"][-1]["cache_control"] == CACHED
    assert sent[2] == {"role": "user", "content": "LIVE\n\nyes"}


async def test_gemini_gets_the_conversation_as_user_and_model_turns() -> None:
    client, models = gemini(["Hi."], model_turn())
    history = (ChatTurn("assistant", "Ready?"), ChatTurn("user", "okay"))
    _ = [chunk async for chunk in client.stream_text("Rules.", "now?", 50, history)]
    contents = models.calls[0].contents
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[0].parts[0].text == OPENING_LINE
    # Their unanswered line and the new message share one turn.
    assert [p.text for p in contents[2].parts] == ["okay", "now?"]

    chat = client.tool_chat("Rules.", TOOLS, 50, (ChatTurn("user", "hi"), history[0]))
    with pytest.raises(Exception):  # noqa: B017 - the fake reply has no parts; only the request matters.
        await chat.send("go")
    assert [c.role for c in models.calls[1].contents] == ["user", "model", "user"]
