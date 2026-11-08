"""Watching the game more often for a few seconds, by rule on danger or when a player turn asks."""

import asyncio
import time
from collections.abc import Sequence

import numpy as np

from brain.agent.focus_tool import WatchInput, watch_tool
from brain.agent.tools import Tool, ToolRegistry, TurnContext
from brain.agent.turn import run_turn
from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus
from brain.llm.base import ChatTurn, SchemaT, System, ToolCall, ToolDeclaration, ToolStep
from brain.memory.layers import TalkerContext
from brain.perception.focus import ENDED_NOTICE_S, Focus, FocusIntervals
from brain.perception.observer import Observer
from brain.perception.tracker import ObservationTracker
from brain.tests.test_observer import report


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def focus(clock: Clock | None = None, intervals: FocusIntervals | None = None) -> Focus:
    return Focus(intervals or FocusIntervals(1.3, 0.8, 0.6), 5.0, clock or Clock())


def test_default_is_the_slow_rate() -> None:
    built = focus()
    assert built.level() == "low"
    assert built.interval_s() == 1.3
    assert built.live_state() == {}


def test_a_boost_lasts_its_hold_then_drops_back_by_itself() -> None:
    clock = Clock()
    built = focus(clock)
    built.boost("medium", "player turn")
    assert built.interval_s() == 0.8
    assert built.live_state()["watching"].startswith("closely (medium, 5 s left")

    clock.now += 5.1
    assert built.interval_s() == 1.3
    assert "nothing to say or do" in built.live_state()["watching"]
    clock.now += ENDED_NOTICE_S
    assert built.live_state() == {}


def test_repeating_a_boost_restarts_the_hold_instead_of_adding() -> None:
    clock = Clock()
    built = focus(clock)
    built.boost("high", "player turn")
    clock.now += 4.0
    built.boost("high", "player turn")
    clock.now += 4.0
    assert built.level() == "high"
    clock.now += 1.1
    assert built.level() == "low"


def test_the_highest_boost_wins_and_one_ending_keeps_the_other() -> None:
    clock = Clock()
    built = focus(clock)
    built.boost("high", "player turn")
    clock.now += 3.0
    built.boost("medium", "fight")
    assert built.level() == "high"
    clock.now += 2.1
    assert built.level() == "medium"


def observer(built_focus: Focus, vision: object | None = None) -> tuple[Observer, RingBuffer]:
    buffer = RingBuffer(5)
    built = Observer(
        buffer,
        type("Overlay", (), {"display_scale": 1.0})(),
        vision or object(),  # type: ignore[arg-type]
        EventBus(),
        ObservationTracker(),
        built_focus,
        1280,
        0,
    )
    return built, buffer


def test_one_frame_reporting_danger_looks_again_sooner() -> None:
    built_focus = focus()
    built, _ = observer(built_focus)
    built._apply(report("medium"), 1.0)
    assert built_focus.level() == "medium"


def test_confirmed_high_danger_watches_at_the_highest_rate() -> None:
    built_focus = focus()
    built, _ = observer(built_focus)
    built._apply(report("high"), 1.0)
    built._apply(report("high"), 1.6)
    assert built_focus.level() == "high"
    assert "fight" in built.live_state()["watching"]


def test_calm_frames_do_not_boost() -> None:
    built_focus = focus()
    built, _ = observer(built_focus)
    built._apply(report("none"), 1.0)
    built._apply(report("none"), 2.3)
    assert built_focus.level() == "low"


class CountingVision:
    def __init__(self) -> None:
        self.calls = 0

    async def vision_json(
        self, prompt: str, image: bytes, media_type: str, schema: type[SchemaT], max_tokens: int
    ) -> SchemaT:
        self.calls += 1
        return report("none")  # type: ignore[return-value]


async def test_a_boost_mid_wait_looks_sooner_instead_of_waiting_out_the_slow_rate() -> None:
    built_focus = Focus(FocusIntervals(30.0, 0.02, 0.02), 5.0)
    vision = CountingVision()
    built, buffer = observer(built_focus, vision)
    image = np.full((72, 128, 3), 200, dtype=np.uint8)
    buffer.push(Frame(time.monotonic(), image))
    running = asyncio.create_task(built.run())
    await asyncio.sleep(0.1)
    assert vision.calls == 1

    buffer.push(Frame(time.monotonic(), image))
    built_focus.boost("medium", "player turn")
    await asyncio.sleep(0.2)
    running.cancel()
    assert vision.calls == 2


async def test_the_tool_boosts_and_says_there_is_nothing_to_announce() -> None:
    built_focus = focus()
    tool = watch_tool(built_focus)
    text = await tool.handler(WatchInput(level="high"), TurnContext())
    assert built_focus.level() == "high"
    assert "nothing to say" in text


class ScriptedChat:
    def __init__(self, steps: list[ToolStep]) -> None:
        self.steps = steps

    async def send(self, text: str) -> ToolStep:
        return self.steps.pop(0)

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep:
        return self.steps.pop(0)


class ScriptedLLM:
    def __init__(self, steps: list[ToolStep]) -> None:
        self.steps = steps

    def tool_chat(
        self,
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> ScriptedChat:
        return ScriptedChat(self.steps)


async def turn_with(call: str, registry: ToolRegistry) -> int:
    announced = 0

    async def looking() -> None:
        nonlocal announced
        announced += 1

    steps = [ToolStep("", (ToolCall(call, {"level": "medium"}),)), ToolStep("On it.")]
    await run_turn(
        ScriptedLLM(steps),
        registry,
        "watch this",
        "",
        "",
        100,
        TalkerContext(),
        TurnContext(),
        looking,
        "Ok.",
    )
    return announced


async def test_a_quick_tool_skips_the_one_sec_line_and_a_slow_one_does_not() -> None:
    async def slow(_arguments: WatchInput, _turn: TurnContext) -> str:
        return "done"

    registry = ToolRegistry([watch_tool(focus()), Tool("slow_look", "Looks.", WatchInput, slow)])
    assert await turn_with("watch_closely", registry) == 0
    assert await turn_with("slow_look", registry) == 1
