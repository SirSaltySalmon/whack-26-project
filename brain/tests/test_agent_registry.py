"""The registry's promise: a tool always comes back as text, unless the turn is being cancelled."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, ToolRegistry, TurnContext
from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, ToolCall
from brain.perception.closeup import AREA_NAMES
from brain.tests.agent_rig import BOTH_VISION_TOOLS, rig
from brain.tests.fakes import FakeTextLLM, FakeVision, make_frame

EXPECTED_ARGUMENTS = {
    "look_closer": {"question", "area"},
    "point_at": {"target"},
    "lookup_wiki": {"topic", "question", "open_page"},
    "read_open_page": {"question"},
    "note_unknown": {"subject", "attribute", "question"},
    "think_hard": {"question"},
    "look_back": {"question"},
    "answer_question": {"question_id", "answer", "correction"},
    "remember_fact": {"subject", "attribute", "value"},
    "forget_fact": {"subject", "attribute"},
}
# Database writes that finish at once, so they play no filler and don't hold off a barge-in.
QUICK_TOOLS = {"answer_question", "remember_fact", "forget_fact"}
Handler = Callable[["ValueInput", TurnContext], Awaitable[str]]


class ValueInput(BaseModel):
    value: int


def registry_with(handler: Handler, timeout_s: float = 1.0) -> ToolRegistry:
    return ToolRegistry([Tool("demo", "A tool.", ValueInput, handler, timeout_s)])


async def run_demo(handler: Handler, timeout_s: float = 1.0) -> str:
    return await registry_with(handler, timeout_s).run(
        ToolCall("demo", {"value": 1}), TurnContext()
    )


def no_key() -> FakeVision:
    raise LLMUnavailableError("GEMINI_API_KEY isn't set")


def no_deep_key() -> FakeTextLLM:
    raise LLMUnavailableError("GEMINI_API_KEY isn't set")


async def test_a_tool_gets_its_validated_input_and_the_turn() -> None:
    seen: list[tuple[int, TurnContext]] = []

    async def handler(arguments: ValueInput, turn: TurnContext) -> str:
        seen.append((arguments.value, turn))
        return "ran"

    turn = TurnContext(started_at=3.0)
    assert await registry_with(handler).run(ToolCall("demo", {"value": 5}), turn) == "ran"
    assert seen == [(5, turn)]


async def test_an_unknown_tool_returns_text() -> None:
    output = await ToolRegistry([]).run(ToolCall("mystery", {}), TurnContext())
    assert output == "There's no tool called mystery."


async def test_invalid_arguments_return_text_and_never_reach_the_tool() -> None:
    ran: list[int] = []

    async def handler(arguments: ValueInput, _: TurnContext) -> str:
        ran.append(arguments.value)
        return "ran"

    output = await registry_with(handler).run(ToolCall("demo", {"value": "many"}), TurnContext())
    assert output == "demo was given invalid arguments."
    assert ran == []


async def test_a_tool_that_takes_too_long_returns_text() -> None:
    async def handler(_: ValueInput, __: TurnContext) -> str:
        await asyncio.Event().wait()
        return "never"

    assert await run_demo(handler, timeout_s=0.01) == "demo took too long and was stopped."


@pytest.mark.parametrize(
    ("error", "output"),
    [
        (LLMUnavailableError("over quota"), "demo isn't available right now."),
        (LLMEmptyResponseError("blocked"), "demo isn't available right now."),
        (ValueError("boom"), "demo failed."),
    ],
    ids=["unavailable", "empty", "exception"],
)
async def test_a_failing_tool_returns_text(error: Exception, output: str) -> None:
    async def handler(_: ValueInput, __: TurnContext) -> str:
        raise error

    assert await run_demo(handler) == output


async def test_an_unexpected_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(_: ValueInput, __: TurnContext) -> str:
        raise ValueError("boom")

    await run_demo(handler)
    assert "Tool demo failed" in caplog.text and "boom" in caplog.text


async def test_cancelling_a_tool_isnt_swallowed_because_barge_in_depends_on_it() -> None:
    entered = asyncio.Event()

    async def handler(_: ValueInput, __: TurnContext) -> str:
        entered.set()
        await asyncio.Event().wait()
        return "never"

    task = asyncio.create_task(run_demo(handler, timeout_s=5.0))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_only_the_memory_tools_are_quick() -> None:
    registry = rig().tools.registry()
    quick = {name for name in registry.names if registry.is_quick(ToolCall(name, {}))}
    assert quick == QUICK_TOOLS


def test_only_offers_just_the_tools_named() -> None:
    registry = rig().tools.registry()
    assert registry.only("point_at").names == ("point_at",)
    assert [d.name for d in registry.only("point_at").declarations()] == ["point_at"]
    assert registry.only("no_such_tool").names == ()


async def test_a_tool_left_out_by_only_cant_be_run() -> None:
    ran: list[int] = []

    async def handler(arguments: ValueInput, _: TurnContext) -> str:
        ran.append(arguments.value)
        return "ran"

    narrowed = registry_with(handler).only("other")
    output = await narrowed.run(ToolCall("demo", {"value": 1}), TurnContext())
    assert output == "There's no tool called demo." and ran == []


async def test_once_runs_each_tool_one_time_even_when_asked_twice_together() -> None:
    ran: list[int] = []

    async def handler(arguments: ValueInput, _: TurnContext) -> str:
        await asyncio.sleep(0)
        ran.append(arguments.value)
        return "ran"

    once = registry_with(handler).once()
    outputs = await asyncio.gather(
        once.run(ToolCall("demo", {"value": 1}), TurnContext()),
        once.run(ToolCall("demo", {"value": 2}), TurnContext()),
    )
    assert ran == [1]
    assert outputs == ["ran", "demo already ran, so reply with what you have."]


async def test_each_once_registry_has_its_own_count() -> None:
    async def handler(_: ValueInput, __: TurnContext) -> str:
        return "ran"

    registry = registry_with(handler)
    for _ in range(2):
        assert await registry.once().run(ToolCall("demo", {"value": 1}), TurnContext()) == "ran"


def test_every_tool_is_declared_with_a_json_schema() -> None:
    declarations = {d.name: d for d in rig().tools.registry().declarations()}
    assert set(declarations) == set(EXPECTED_ARGUMENTS)
    for name, arguments in EXPECTED_ARGUMENTS.items():
        declaration = declarations[name]
        assert declaration.description
        assert declaration.parameters["type"] == "object"
        assert set(declaration.parameters["properties"]) == arguments
        assert set(declaration.parameters["required"]) == arguments
        # The model has only these to go on when it fills the arguments in.
        assert all(p["description"] for p in declaration.parameters["properties"].values())


def test_the_area_argument_offers_every_area_a_closeup_can_crop() -> None:
    look = next(d for d in rig().tools.registry().declarations() if d.name == "look_closer")
    assert look.parameters["properties"]["area"]["enum"] == list(AREA_NAMES)


@pytest.mark.parametrize(("tool", "arguments"), BOTH_VISION_TOOLS)
async def test_a_missing_vision_key_becomes_text_and_shows_nothing(
    tool: str, arguments: dict[str, str]
) -> None:
    r = rig(make_frame(), get_vision=no_key)
    assert await r.run(tool, **arguments) == f"{tool} isn't available right now."
    assert r.overlay.sent == []


@pytest.mark.parametrize(("tool", "arguments"), BOTH_VISION_TOOLS)
@pytest.mark.parametrize(
    "error",
    [LLMUnavailableError("over quota"), LLMEmptyResponseError("blocked")],
    ids=["over quota", "empty reply"],
)
async def test_a_vision_outage_becomes_text_and_shows_nothing(
    tool: str, arguments: dict[str, str], error: Exception
) -> None:
    r = rig(make_frame(), reply=error)
    assert await r.run(tool, **arguments) == f"{tool} isn't available right now."
    assert r.overlay.sent == []


@pytest.mark.parametrize(("tool", "arguments"), BOTH_VISION_TOOLS)
async def test_vision_output_of_the_wrong_shape_becomes_text(
    tool: str, arguments: dict[str, str]
) -> None:
    r = rig(make_frame(), reply={"unexpected": True})
    assert await r.run(tool, **arguments) == f"{tool} failed."
    assert r.overlay.sent == []


async def test_a_missing_deep_key_becomes_text_and_shows_nothing() -> None:
    r = rig(get_deep=no_deep_key)
    assert await r.run("think_hard", question="why?") == "think_hard isn't available right now."
    assert r.overlay.sent == []


async def test_an_over_quota_deep_model_becomes_text_and_shows_nothing() -> None:
    r = rig(deep=FakeTextLLM(error=LLMUnavailableError("over quota")))
    assert await r.run("think_hard", question="why?") == "think_hard isn't available right now."
    assert r.overlay.sent == []
