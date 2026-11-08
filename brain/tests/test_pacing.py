"""The player's pacing settings: what the director's rules take from them, and when."""

from brain.director.rules import (
    AskQuestion,
    DirectorState,
    GiveAdvice,
    PlayBark,
    ReactToEvent,
    apply_pacing,
    decide,
)
from brain.events import GameEvent, OverlayConnected, SettingsChanged, Tick
from shared.protocol.messages import Pacing, Settings

# The first question needs only a quiet stretch, so tip tests keep both out of reach.
NO_QUESTIONS = {"question_gap_s": 1e9, "question_quiet_s": 1e9}


def changed(ts: float, **pacing: float) -> SettingsChanged:
    return SettingsChanged(settings=Settings(pacing=Pacing(**pacing)), ts=ts)


def connected(state: DirectorState, ts: float = 0.0) -> DirectorState:
    decide(OverlayConnected(display_scale=1.0, ts=ts), state)
    return state


def test_the_rules_start_from_the_settings_defaults() -> None:
    state, pacing = DirectorState(), Pacing()
    assert state.bark_cooldown_s == pacing.event_gap_s
    assert state.question_gap_s == pacing.question_gap_s
    assert state.question_quiet_s == pacing.question_quiet_s
    assert state.advice_gap_s == pacing.advice_gap_s
    assert state.advice_quiet_s == pacing.advice_quiet_s
    assert state.advice_first_s == pacing.advice_first_s


def test_a_shorter_event_gap_lets_the_next_reaction_through() -> None:
    state = DirectorState(bark_cooldown_s=8.0)
    assert isinstance(decide(GameEvent("hit", ts=0.0), state)[0], ReactToEvent | PlayBark)
    assert decide(GameEvent("hit", ts=3.0), state) == []
    decide(changed(3.5, event_gap_s=2.0), state)
    assert decide(GameEvent("hit", ts=4.0), state) != []


def test_a_shorter_question_gap_and_quiet_stretch_apply_at_once() -> None:
    state = connected(DirectorState(question_gap_s=90.0, question_quiet_s=20.0, advice_gap_s=0))
    state.last_question_at = 0.0
    assert decide(Tick(ts=30.0), state) == []
    decide(changed(31.0, question_gap_s=30.0, question_quiet_s=5.0, advice_gap_s=0), state)
    assert decide(Tick(ts=32.0), state) == [AskQuestion()]


def test_a_shorter_first_tip_brings_the_first_tip_forward() -> None:
    state = connected(DirectorState(**NO_QUESTIONS, advice_first_s=90.0, advice_quiet_s=0))
    decide(changed(10.0, **NO_QUESTIONS, advice_first_s=5.0, advice_quiet_s=0), state)
    assert decide(Tick(ts=14.9), state) == []
    assert decide(Tick(ts=15.0), state) == [GiveAdvice()]


def test_a_shorter_tip_gap_brings_the_next_tip_forward() -> None:
    state = connected(
        DirectorState(**NO_QUESTIONS, advice_first_s=10.0, advice_gap_s=180.0, advice_quiet_s=0)
    )
    assert decide(Tick(ts=10.0), state) == [GiveAdvice()]
    decide(changed(20.0, **NO_QUESTIONS, advice_gap_s=30.0, advice_quiet_s=0), state)
    assert decide(Tick(ts=49.9), state) == []
    assert decide(Tick(ts=50.0), state) == [GiveAdvice()]


def test_a_longer_gap_never_pushes_back_a_tip_already_due() -> None:
    state = connected(DirectorState(**NO_QUESTIONS, advice_first_s=20.0, advice_quiet_s=0))
    decide(changed(5.0, **NO_QUESTIONS, advice_first_s=600.0, advice_quiet_s=0), state)
    assert decide(Tick(ts=20.0), state) == [GiveAdvice()]


def test_changing_another_setting_leaves_a_scheduled_tip_alone() -> None:
    state = connected(DirectorState(**NO_QUESTIONS, advice_first_s=60.0, advice_quiet_s=0))
    pacing = Pacing(**NO_QUESTIONS, advice_first_s=60.0, advice_quiet_s=0)
    decide(SettingsChanged(settings=Settings(personality="calm", pacing=pacing), ts=30.0), state)
    assert state.next_advice_at == 60.0


def test_a_zero_tip_gap_turns_tips_off_when_changed_live() -> None:
    state = connected(DirectorState(**NO_QUESTIONS, advice_first_s=10.0, advice_quiet_s=0))
    decide(changed(5.0, **NO_QUESTIONS, advice_gap_s=0), state)
    assert decide(Tick(ts=1_000.0), state) == []


def test_without_a_time_only_the_gaps_change() -> None:
    state = connected(DirectorState(advice_first_s=90.0))
    apply_pacing(state, Pacing(advice_first_s=5.0))
    assert state.next_advice_at == 90.0
    assert state.advice_first_s == 5.0
