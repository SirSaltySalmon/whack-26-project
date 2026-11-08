"""The debug panel: why the director did what it did, and what the brain hears and does."""

import asyncio
import logging

import pytest

from brain.debug_panel import BrainPanel, tool_line
from brain.director.rules import (
    AskQuestion,
    AskTalker,
    CancelSpeech,
    DirectorState,
    GiveAdvice,
    PlayBark,
    ReactToEvent,
    Say,
    StopSpeaking,
)
from brain.director.why import explain
from brain.events import (
    EventBus,
    GameEvent,
    OverlayConnected,
    PlayerMood,
    PlayerSpeech,
    PlayerSpeechPartial,
    PlayerStartedSpeaking,
    SettingsChanged,
    Tick,
)
from shared.protocol.messages import BrainMessageAdapter, DebugBrain

DANGER = GameEvent("danger_started", {})
BARK = PlayBark("danger", "danger_started", {})
REACT = ReactToEvent("danger_started", {})


def state(paused: bool = False) -> DirectorState:
    s = DirectorState()
    s.paused = paused
    return s


@pytest.mark.parametrize(
    ("event", "actions", "busy", "paused", "said"),
    [
        (DANGER, [BARK], False, False, "danger started: quick line"),
        (DANGER, [REACT], False, False, "danger started: reacting"),
        (DANGER, [REACT], True, False, "danger started: skipped, already talking"),
        (DANGER, [], False, False, "danger started: quiet, cooling down"),
        (DANGER, [], False, True, "danger started: quiet, paused"),
        (PlayerSpeech("hi"), [AskTalker("hi", None)], False, False, "answering you"),
        (PlayerSpeech("hi"), [], False, True, "heard you, but paused"),
        (PlayerStartedSpeaking(), [CancelSpeech()], True, False, "listening: stopped talking"),
        (PlayerStartedSpeaking(), [CancelSpeech()], False, False, "listening"),
        (Tick(), [AskQuestion()], False, False, "asking you a question"),
        (Tick(), [GiveAdvice()], False, False, "offering a tip"),
        (OverlayConnected(1.0), [Say("Brain connected.")], False, False, "greeting"),
        (SettingsChanged(object()), [StopSpeaking()], False, False, "paused by you"),
    ],
)
def test_each_decision_is_explained_in_a_few_words(
    event: object, actions: list[object], busy: bool, paused: bool, said: str
) -> None:
    assert explain(event, actions, busy, state(paused)) == said  # type: ignore[arg-type]


def test_a_tick_that_decides_nothing_shows_nothing() -> None:
    # Ticks come every few seconds, and would wipe out the decision worth reading.
    assert explain(Tick(), [], False, state()) is None


def test_tools_read_as_short_lines_with_their_subject() -> None:
    wiki = {"topic": "Life Crystal", "question": "x"}
    assert tool_line("lookup_wiki", wiki) == "wiki: Life Crystal"
    assert tool_line("look_closer", {"question": "what's that"}) == "looking closer"
    assert tool_line("point_at", {"target": " "}) == "pointing"
    assert tool_line("brand_new_tool", {}) == "brand new tool"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_the_snapshot_holds_what_was_heard_decided_done_and_timed() -> None:
    clock = Clock()
    panel = BrainPanel(clock)
    panel.note_event(PlayerSpeechPartial("what's the best"))
    assert panel.snapshot().hearing_live
    panel.note_event(PlayerSpeech("what's the best boss?"))
    panel.note_event(PlayerMood("positive", 0.6, 0.4))
    panel.note_decision(PlayerSpeech("x"), [AskTalker("x", None)], False, state())
    panel.note_record("Tool %s: %s", ("lookup_wiki", {"topic": "Boss"}))
    panel.note_record("Watching the game at %s focus", ("medium",))
    panel.note_record("Latency: end of turn to first audio %.0f ms", (1125.4,))
    panel.note_record(
        "Latency: frame to %s %.0f ms (%s from %s: noticed in %.0f, spoke in %.0f)",
        ("bark", 182.0, "danger_started", "reader", 90.0, 92.0),
    )
    snap = panel.snapshot()
    assert snap.hearing == "what's the best boss?" and not snap.hearing_live
    assert (snap.mood, snap.mood_valence) == ("positive", 0.6)
    assert snap.decision == "answering you"
    assert snap.doing == "wiki: Boss" and snap.focus == "medium"
    timed = [(shown.label, shown.ms) for shown in snap.latency]
    assert timed == [("frame → bark", 182), ("you stopped → voice", 1125)]
    clock.now += 7  # A tool's line fades a few seconds after it starts
    assert panel.snapshot().doing is None


def test_only_the_newest_three_latencies_show_and_a_repeat_moves_to_the_front() -> None:
    panel = BrainPanel(Clock())
    panel.note_record("Latency: event to bark %.0f ms (%s)", (40.0, "danger_started"))
    panel.note_record("Latency: player turn took %.0f ms", (900.0,))
    panel.note_record("Latency: end of turn to first audio %.0f ms", (1100.0,))
    panel.note_record("Latency: frame to %s %.0f ms (%s)", ("bark", 150.0, "x"))
    panel.note_record("Latency: event to bark %.0f ms (%s)", (35.0, "danger_started"))
    labels = [shown.label for shown in panel.snapshot().latency]
    assert labels == ["event → bark", "frame → bark", "you stopped → voice"]


def test_unrelated_and_malformed_records_are_ignored() -> None:
    panel = BrainPanel(Clock())
    panel.note_record("Tool %s timed out after %.0f s", ("look_closer", 10.0))
    panel.note_record("Latency: player turn took %.0f ms", ("soon",))
    panel.note_record("Something else entirely", ())
    assert panel.snapshot() == DebugBrain()


def test_the_snapshot_is_a_valid_brain_message() -> None:
    message = BrainPanel(Clock()).snapshot().model_dump_json()
    assert isinstance(BrainMessageAdapter.validate_json(message), DebugBrain)


async def test_the_panel_hears_the_bus_and_the_logs_and_sends_snapshots(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="brain")  # As the live brain logs
    bus = EventBus()
    panel = BrainPanel()
    sent: list[DebugBrain] = []

    async def send(message: object) -> None:
        sent.append(message)  # type: ignore[arg-type]

    task = asyncio.create_task(panel.run(bus, send))
    await asyncio.sleep(0)
    bus.publish(PlayerSpeech("is it night yet?"))
    logging.getLogger("brain.agent.tools").info("Tool %s: %s", "look_closer", {"question": "x"})
    for _ in range(50):
        await asyncio.sleep(0.02)
        if sent and sent[-1].hearing and sent[-1].doing:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sent[-1].hearing == "is it night yet?" and sent[-1].doing == "looking closer"
    # Stopping takes the log handler away again.
    assert panel.handler not in logging.getLogger("brain").handlers
