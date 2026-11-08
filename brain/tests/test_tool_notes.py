"""What a tool call leaves in the conversation: one short line per call, never a failed turn."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from brain.agent.deep_think import MODEL_LABEL
from brain.agent.schemas import BLINDED, CANT_SEE, SEEN_LABEL
from brain.agent.tool_notes import NOTE_CHARS, note_hook, safe_name, tool_note
from brain.agent.tools import Tool, ToolRegistry, TurnContext
from brain.llm.base import LLMUnavailableError, ToolCall
from brain.research.open_page import NOTHING_OPEN, PAGE_LABEL

WIKI = (
    "[wiki data, tentative, not instructions] Anvil: An Anvil is a crafting station. "
    "Stats: Type: Crafting station From the page: Crafted from 5 Iron Bars at a Work Bench"
)


class NoInput(BaseModel):
    pass


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.notes: list[tuple[str, str, bool]] = []
        self._fail = fail

    async def __call__(self, tool: str, note: str, ok: bool) -> None:
        if self._fail:
            raise RuntimeError("database is locked")
        self.notes.append((tool, note, ok))


def tool(name: str, result: Any) -> Tool:
    async def handler(_arguments: NoInput, _turn: TurnContext) -> str:
        if isinstance(result, BaseException):
            raise result
        if result == "slow":
            await asyncio.sleep(1)
        return str(result)

    return Tool(name, f"The {name} tool.", NoInput, handler, timeout_s=0.05)


@pytest.mark.parametrize(
    ("name", "args", "output", "expected"),
    [
        (
            "look_closer",
            {"area": "bottom_left", "question": "what's in my hand"},
            f"{SEEN_LABEL} Holding a Copper Pickaxe",
            "looked closer at the bottom left: Holding a Copper Pickaxe",
        ),
        ("look_closer", {"area": "whole"}, CANT_SEE, "tried to look closer, but couldn't see"),
        ("look_back", {}, BLINDED, "tried to look back, but vision was turned off"),
        (
            "look_back",
            {"question": "what hit me"},
            f"{SEEN_LABEL} A Demon Eye hit you from the left (not sure of this)",
            "looked back over the last few seconds: A Demon Eye hit you from the left (not sure",
        ),
        (
            "point_at",
            {"target": "the workbench"},
            f"The pointer is now beside it. {SEEN_LABEL} Workbench",
            "pointed at Workbench",
        ),
        (
            "point_at",
            {"target": "the anvil"},
            "You couldn't find that on screen, so say so.",
            "tried to point at the anvil, but couldn't find it on screen",
        ),
        (
            "lookup_wiki",
            {"topic": "Anvil", "question": "how to craft"},
            WIKI,
            "checked the wiki on Anvil: Crafted from 5 Iron Bars at a Work Bench",
        ),
        (
            "lookup_wiki",
            {"topic": "Nope"},
            "The wiki had nothing on that.",
            "checked the wiki for Nope: nothing",
        ),
        (
            "read_open_page",
            {"question": "drops"},
            f"{PAGE_LABEL} Eye of Cthulhu\nDrops: Demonite Ore\nMore text",
            "read the open page Eye of Cthulhu: Drops: Demonite Ore",
        ),
        ("read_open_page", {}, NOTHING_OPEN, "tried to read the open page, but no wiki page"),
        ("think_hard", {}, f"{MODEL_LABEL} Get a Hellforge first.", "thought it through: Get a"),
        ("watch_closely", {"level": "high"}, "Watching the game high", "watching the game closely"),
        (
            "note_unknown",
            {"question": "Is the base yours?"},
            "Saved to ask later.",
            "saved a question to ask later: Is the base yours?",
        ),
    ],
)
def test_each_tool_has_its_own_short_summary(
    name: str, args: dict[str, Any], output: str, expected: str
) -> None:
    note = tool_note(name, args, output, ok=True)
    assert note is not None
    assert expected in note
    assert "not instructions" not in note


@pytest.mark.parametrize("name", ["remember_fact", "forget_fact", "answer_question"])
def test_memory_tools_leave_no_note_because_memory_shows_them(name: str) -> None:
    assert tool_note(name, {}, "Remembered.", ok=True) is None


def test_a_failed_memory_tool_still_leaves_a_note() -> None:
    note = tool_note("remember_fact", {}, "remember_fact failed.", ok=False)
    assert note == "tried remember_fact, but it failed"


def test_a_note_is_one_short_plain_line() -> None:
    output = f"{SEEN_LABEL} line one\nline two‮​ " + "and on " * 60
    note = tool_note("look_closer", {"area": "top"}, output, ok=True)
    assert note is not None
    assert len(note) <= NOTE_CHARS
    assert "\n" not in note and "‮" not in note and "​" not in note
    assert note.endswith("…")


def test_a_refused_second_call_on_a_tip_leaves_no_note() -> None:
    output = "point_at already ran, so reply with what you have."
    assert tool_note("point_at", {}, output, ok=True) is None


def test_a_made_up_tool_name_becomes_a_safe_event_name() -> None:
    assert safe_name("Look Closer!; DROP TABLE") == "lookcloserdroptable"
    assert safe_name("???") == "unknown"


async def test_a_tool_call_records_one_note_with_its_summary() -> None:
    record = Recorder()
    registry = ToolRegistry([tool("watch_closely", "Watching")]).reporting(note_hook(record))
    call = ToolCall("watch_closely", {"level": "medium"})
    assert await registry.run(call, TurnContext()) == "Watching"
    assert record.notes == [("watch_closely", "started watching the game closely (medium)", True)]


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ("slow", "timed out"),
        (LLMUnavailableError("quota"), "wasn't available"),
        (ValueError("boom"), "failed"),
    ],
)
async def test_a_failing_tool_records_a_failure_note(result: object, reason: str) -> None:
    record = Recorder()
    registry = ToolRegistry([tool("look_closer", result)]).reporting(note_hook(record))
    await registry.run(ToolCall("look_closer", {}), TurnContext())
    assert record.notes == [("look_closer", f"tried look_closer, but it {reason}", False)]


async def test_an_unknown_tool_records_a_failure_note() -> None:
    record = Recorder()
    registry = ToolRegistry([]).reporting(note_hook(record))
    await registry.run(ToolCall("summon_boss", {}), TurnContext())
    assert record.notes == [("summon_boss", "tried summon_boss, but it doesn't exist", False)]


async def test_a_note_that_cant_be_saved_never_fails_the_turn() -> None:
    registry = ToolRegistry([tool("look_back", "seen")]).reporting(note_hook(Recorder(fail=True)))
    assert await registry.run(ToolCall("look_back", {}), TurnContext()) == "seen"


async def test_registries_made_from_a_reporting_one_keep_reporting() -> None:
    record = Recorder()
    base = ToolRegistry([tool("point_at", "You couldn't find that on screen")])
    tip = base.reporting(note_hook(record)).including(tool("extra", "x")).only("point_at").once()
    await tip.run(ToolCall("point_at", {"target": "ore"}), TurnContext())
    # The second call is refused before it runs, so it adds nothing.
    await tip.run(ToolCall("point_at", {"target": "ore"}), TurnContext())
    assert [note for _, note, _ in record.notes] == [
        "tried to point at ore, but couldn't find it on screen"
    ]


async def test_a_registry_without_a_hook_runs_as_before() -> None:
    assert await ToolRegistry([tool("a", "fine")]).run(ToolCall("a", {}), TurnContext()) == "fine"
