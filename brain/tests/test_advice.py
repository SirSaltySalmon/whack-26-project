"""Occasional tips on what to do next: when the rules offer one, and what the director does."""

from brain.director.rules import AskQuestion, DirectorState, GiveAdvice, decide
from brain.director.talker import ADVICE_PROMPT
from brain.events import GameEvent, OverlayConnected, Tick
from brain.tests.director_rig import Rig
from brain.tests.fakes import FakeTextLLM

GAP_S = 300.0
QUIET_S = 30.0
GREETING = "Brain connected."


def advising(at: float = 0.0) -> DirectorState:
    # No question would ever be due in these, so only the advice rules are in play.
    state = DirectorState(
        question_gap_s=1e9, question_quiet_s=1e9, advice_gap_s=GAP_S, advice_quiet_s=QUIET_S
    )
    decide(OverlayConnected(display_scale=1.0, ts=at), state)
    state.last_question_at = -1e9
    return state


def test_the_first_tip_waits_a_full_gap_after_the_player_arrives() -> None:
    state = advising()
    assert decide(Tick(ts=QUIET_S), state) == []  # Starts the clock
    assert decide(Tick(ts=QUIET_S + GAP_S - 0.1), state) == []
    assert decide(Tick(ts=QUIET_S + GAP_S), state) == [GiveAdvice()]
    assert decide(Tick(ts=QUIET_S + GAP_S + 5), state) == []


def test_no_tip_in_danger_or_right_after_activity() -> None:
    state = advising()
    decide(Tick(ts=QUIET_S), state)
    decide(GameEvent("danger_started", ts=GAP_S), state)
    assert decide(Tick(ts=GAP_S * 2), state) == []
    decide(GameEvent("danger_ended", ts=GAP_S * 2), state)
    assert decide(Tick(ts=GAP_S * 2 + QUIET_S - 1), state) == []
    assert decide(Tick(ts=GAP_S * 2 + QUIET_S), state) == [GiveAdvice()]


def test_a_due_question_comes_before_a_tip() -> None:
    state = DirectorState(
        question_gap_s=90.0, question_quiet_s=20.0, advice_gap_s=GAP_S, advice_quiet_s=QUIET_S
    )
    decide(OverlayConnected(display_scale=1.0, ts=0.0), state)
    state.last_advice_at = -GAP_S
    assert decide(Tick(ts=40.0), state) == [AskQuestion()]
    # Too soon after the question to talk over its answer.
    assert decide(Tick(ts=45.0), state) == []
    assert decide(Tick(ts=40.0 + QUIET_S), state) == [GiveAdvice()]


def test_a_zero_gap_turns_tips_off() -> None:
    state = advising()
    state.advice_gap_s = 0
    for ts in (QUIET_S, 10_000.0, 20_000.0):
        assert decide(Tick(ts=ts), state) == []


async def due_tip(rig: Rig) -> None:
    await rig.publish(OverlayConnected(display_scale=1.0, ts=0.0))
    await rig.publish(Tick(ts=QUIET_S))
    await rig.publish(Tick(ts=QUIET_S + GAP_S))


async def test_a_tip_is_spoken_from_the_advice_prompt() -> None:
    talker = FakeTextLLM(["Try the dungeon next."])
    rig = Rig(talker=talker, advice_gap_s=GAP_S, quiet_s=1e9)
    async with rig.running():
        await due_tip(rig)
    assert talker.prompts == [ADVICE_PROMPT]
    assert rig.voice.said == [GREETING, "Try the dungeon next."]


async def test_skip_stays_quiet() -> None:
    rig = Rig(talker=FakeTextLLM(["SKIP."]), advice_gap_s=GAP_S, quiet_s=1e9)
    async with rig.running():
        await due_tip(rig)
    assert rig.voice.said == [GREETING]


async def test_hints_off_means_no_tips_and_no_model_call() -> None:
    talker = FakeTextLLM(["Try the dungeon next."])
    rig = Rig(talker=talker, advice_gap_s=GAP_S, quiet_s=1e9, proactive=False)
    async with rig.running():
        await due_tip(rig)
    assert talker.prompts == [] and rig.voice.said == [GREETING]
