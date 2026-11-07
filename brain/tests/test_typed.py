import asyncio
import logging
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import brain.__main__ as entry_point
from brain.agent.tools import Tool, ToolRegistry, TurnContext
from brain.app import run
from brain.config import Settings
from brain.director.director import Director
from brain.events import Event, EventBus, PlayerSpeech, PlayerStartedSpeaking
from brain.llm.base import ToolCall, ToolStep
from brain.tests.fakes import FakeVoice, ScriptedToolLLM, drain
from brain.voice.typed import MAX_DELAY_S, parse_typed_line, typed_turns


def script(*lines: str, end: Exception | None = None) -> Callable[[], str]:
    """A read_line that gives these lines, then raises `end`, or reports end of input."""
    remaining = iter(lines)

    def read_line() -> str:
        for line in remaining:
            return line
        raise end or EOFError

    return read_line


async def turns_from(*lines: str) -> list[Event]:
    bus = EventBus()
    events = bus.subscribe()
    await asyncio.wait_for(typed_turns(bus, script(*lines)), timeout=5)
    return drain(events)


def transcripts(events: list[Event]) -> list[str]:
    return [event.transcript for event in events if isinstance(event, PlayerSpeech)]


async def until(check: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not check():
        assert time.monotonic() < deadline, "Timed out waiting for the condition"
        await asyncio.sleep(0.001)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("what's that", (0.0, "what's that")),
        ("5: what's that", (5.0, "what's that")),
        ("2.5: x", (2.5, "x")),
        ("0: right now", (0.0, "right now")),
        ("  5:    spaced out  ", (5.0, "spaced out")),
        ("5: what's at 12:30", (5.0, "what's at 12:30")),
        (f"{MAX_DELAY_S}: the longest wait", (MAX_DELAY_S, "the longest wait")),
    ],
)
def test_lines_become_a_delay_and_a_transcript(line: str, expected: tuple[float, str]) -> None:
    assert parse_typed_line(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "\t\n", "5:", "5:   ", "2.5:"])
def test_a_line_with_nothing_to_say_counts_as_blank(line: str) -> None:
    assert parse_typed_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "12:30 is late",
        "5:no space after the colon",
        "note: remember this",
        "-5: below zero",
        "inf: not a number",
        "5 : space before the colon",
        "٣: a digit from another script",
        f"{MAX_DELAY_S + 0.5}: just too long to be a wait",
        f"{'9' * 400}: overflows a float",
        "99999:",
    ],
)
def test_anything_else_is_just_what_they_said(line: str) -> None:
    assert parse_typed_line(line) == (0.0, line)


async def test_a_line_starts_a_turn_and_then_says_it() -> None:
    events = await turns_from("what's that")
    assert [type(event) for event in events] == [PlayerStartedSpeaking, PlayerSpeech]
    assert transcripts(events) == ["what's that"]


async def test_the_loop_gets_a_tick_between_the_two_events() -> None:
    order: list[str] = []

    class MarkingBus(EventBus):
        def publish(self, event: Event) -> None:
            order.append(type(event).__name__)
            # Runs on the next loop iteration, so its position shows whether one happened.
            asyncio.get_running_loop().call_soon(order.append, "tick")
            super().publish(event)

    await typed_turns(MarkingBus(), script("hi"))
    assert order[:3] == ["PlayerStartedSpeaking", "tick", "PlayerSpeech"]


async def test_a_delay_holds_back_the_whole_turn() -> None:
    started = time.monotonic()
    events = await turns_from("0.05: what's that")
    assert transcripts(events) == ["what's that"]
    # Below the delay, because the loop may fire up to one clock tick (15.6 ms on Windows) early.
    assert events[0].ts - started >= 0.02


async def test_lines_stay_in_order_when_an_earlier_one_is_waiting() -> None:
    assert transcripts(await turns_from("0.02: first", "second")) == ["first", "second"]


async def test_blank_lines_are_ignored() -> None:
    events = await turns_from("", "   ", "5:", "real one", "")
    assert transcripts(events) == ["real one"]
    assert len(events) == 2


async def test_it_returns_at_the_end_of_input_having_said_nothing() -> None:
    assert await turns_from() == []


async def test_a_read_failure_is_logged_and_ends_typing_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    events = bus.subscribe()
    read_line = script("before it broke", end=OSError("stdin went away"))
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(typed_turns(bus, read_line), timeout=5)
    assert transcripts(drain(events)) == ["before it broke"]
    assert "Couldn't read a typed line" in caplog.text and "stdin went away" in caplog.text


async def test_a_stuck_read_is_on_a_daemon_thread_and_cannot_hold_up_shutdown() -> None:
    release = threading.Event()
    readers: list[threading.Thread] = []

    def stuck_read() -> str:
        readers.append(threading.current_thread())
        release.wait(timeout=5)
        raise EOFError

    typing = asyncio.create_task(typed_turns(EventBus(), stuck_read))
    await until(lambda: bool(readers))
    assert readers[0].daemon and readers[0] is not threading.main_thread()
    typing.cancel()
    await asyncio.gather(typing, return_exceptions=True)
    # Cancelling finished while the read was still stuck, so shutdown never waits for it.
    assert readers[0].is_alive() and not release.is_set()
    release.set()


async def test_the_reader_holds_stdin_so_shutdown_cannot_close_it_under_a_stuck_read() -> None:
    # Only Python before 3.12.10 crashes without this, so check the reference, not the crash.
    held: list[bool] = []

    def read_line() -> str:
        held.append(any(value is sys.stdin for value in sys._getframe(1).f_locals.values()))
        raise EOFError

    await typed_turns(EventBus(), read_line)
    assert held == [True]


def test_a_line_that_arrives_after_shutdown_is_dropped_without_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    readers: list[threading.Thread] = []
    unhandled: list[object] = []
    monkeypatch.setattr(threading, "excepthook", unhandled.append)

    def read_after_the_loop_has_gone() -> str:
        readers.append(threading.current_thread())
        release.wait(timeout=5)
        return "too late"

    async def start_then_stop() -> None:
        typing = asyncio.create_task(typed_turns(EventBus(), read_after_the_loop_has_gone))
        await until(lambda: bool(readers))
        typing.cancel()
        await asyncio.gather(typing, return_exceptions=True)

    asyncio.run(start_then_stop())
    release.set()
    readers[0].join(timeout=5)
    assert not readers[0].is_alive() and unhandled == []


@pytest.mark.parametrize("argv", [["--live"], ["--live", "--type"], ["--replay", "s", "--type"]])
def test_the_type_flag_reaches_run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_run(_settings: object, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(entry_point, "run", fake_run)
    monkeypatch.setattr(entry_point, "Settings", object)
    monkeypatch.setattr(entry_point, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["brain", *argv])
    entry_point.main()
    assert [call["typed"] for call in calls] == ["--type" in argv]


async def _run_brain_briefly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: bool, fake_typing: Any
) -> None:
    """Runs the real wiring, in replay mode because that needs no keys and leaves no trace."""
    up = asyncio.Event()

    async def idle_serve() -> None:
        up.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("brain.app.typed_turns", fake_typing)
    # Stands in for uvicorn, so no socket opens, and says when the brain's tasks are starting.
    monkeypatch.setattr("brain.app.uvicorn.Server", lambda _: SimpleNamespace(serve=idle_serve))
    snapshot = tmp_path / "no-snapshot.sql"
    settings = Settings(_env_file=None, replay_snapshot=snapshot)  # type: ignore[call-arg]
    brain = asyncio.create_task(run(settings, replay_dir=tmp_path, typed=typed))
    try:
        await asyncio.wait_for(up.wait(), timeout=10)
        # The other tasks start right after the server's, so give them a chance to begin.
        for _ in range(5):
            await asyncio.sleep(0)
        assert not brain.done()
    finally:
        brain.cancel()
        await asyncio.gather(brain, return_exceptions=True)


@pytest.mark.parametrize("typed", [True, False])
async def test_the_brain_takes_typed_turns_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: bool
) -> None:
    buses: list[EventBus] = []

    async def fake_typing(bus: EventBus) -> None:
        buses.append(bus)

    await _run_brain_briefly(tmp_path, monkeypatch, typed, fake_typing)
    assert len(buses) == (1 if typed else 0)


async def test_typing_failing_does_not_take_the_brain_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken_typing(_bus: EventBus) -> None:
        raise RuntimeError("no stdin here")

    with caplog.at_level(logging.ERROR):
        # This asserts the brain is still running after typing has failed.
        await _run_brain_briefly(tmp_path, monkeypatch, True, broken_typing)
    assert "Typing stopped" in caplog.text


class _NoInput(BaseModel):
    pass


async def test_a_typed_line_gets_a_spoken_reply_with_the_typed_turns_start_time() -> None:
    bus = EventBus()
    events = bus.subscribe()
    voice = FakeVoice()
    turns: list[TurnContext] = []

    async def look(_arguments: _NoInput, turn: TurnContext) -> str:
        turns.append(turn)
        return "[seen on screen] a slime"

    llm = ScriptedToolLLM([ToolStep("", (ToolCall("look", {}),)), ToolStep("Looks like a slime.")])
    registry = ToolRegistry([Tool("look", "Look at the screen", _NoInput, look)])
    director = Director(bus, voice, proactive=lambda: True, agent=llm, tools=registry)
    running = asyncio.create_task(director.run())
    await typed_turns(bus, script("what's that"))
    await until(lambda: "Looks like a slime." in voice.said)
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)

    assert llm.sends == ["what's that"]
    assert voice.said[-1] == "Looks like a slime."
    started = [event for event in drain(events) if isinstance(event, PlayerStartedSpeaking)]
    assert [turn.started_at for turn in turns] == [started[0].ts]
