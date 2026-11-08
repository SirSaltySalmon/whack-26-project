"""When the rules offer a tip: first after arriving, then on a gap, and sooner once the partner
learns where the player stands. test_director_advice.py covers what the director does with one."""

import pytest

from brain.director.rules import (
    AskQuestion,
    DirectorState,
    GiveAdvice,
    PartnerSpoke,
    decide,
)
from brain.events import (
    FactLearned,
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    Tick,
)

FIRST_S = 90.0
GAP_S = 180.0
QUIET_S = 20.0
AFTER_LEARNING_S = 15.0


def advising(at: float = 0.0, gap_s: float = GAP_S) -> DirectorState:
    # No question is ever due in these, so only the tip rules are in play.
    state = DirectorState(
        question_gap_s=1e9,
        question_quiet_s=1e9,
        advice_gap_s=gap_s,
        advice_quiet_s=QUIET_S,
        advice_first_s=FIRST_S,
        advice_after_learning_s=AFTER_LEARNING_S,
    )
    decide(OverlayConnected(display_scale=1.0, ts=at), state)
    return state


def learned(
    ts: float, subject: str = "playthrough", source: str = "observed", attribute: str = "progress"
) -> FactLearned:
    return FactLearned(subject, attribute, source, "stored", ts=ts)


def test_the_first_tip_comes_a_while_after_the_player_arrives() -> None:
    state = advising()
    assert decide(Tick(ts=FIRST_S - 0.1), state) == []
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]


def test_after_a_tip_the_next_waits_a_full_gap() -> None:
    state = advising()
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]
    assert decide(Tick(ts=FIRST_S + GAP_S - 0.1), state) == []
    assert decide(Tick(ts=FIRST_S + GAP_S), state) == [GiveAdvice()]


def test_reconnecting_doesnt_restart_the_tip_clock() -> None:
    state = advising()
    decide(OverlayConnected(display_scale=1.0, ts=50.0), state)
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]


def test_no_tip_with_no_overlay_connected() -> None:
    state = DirectorState(advice_gap_s=GAP_S)
    decide(learned(1.0, source="player"), state)
    assert decide(Tick(ts=10_000.0), state) == []


@pytest.mark.parametrize(
    "talk",
    [PlayerSpeech(transcript="hi", ts=80.0), PartnerSpoke(ts=80.0)],
    ids=["player_turn", "partner_line"],
)
def test_a_due_tip_waits_for_a_quiet_stretch_after_talk(talk: object) -> None:
    state = advising()
    decide(talk, state)  # type: ignore[arg-type]
    assert decide(Tick(ts=80.0 + QUIET_S - 0.1), state) == []
    assert decide(Tick(ts=80.0 + QUIET_S), state) == [GiveAdvice()]


def test_game_events_alone_dont_hold_a_tip_back() -> None:
    state = advising()
    for ts in range(1, int(FIRST_S), 4):
        decide(GameEvent("something", ts=float(ts)), state)
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]


def test_no_tip_in_danger_and_one_soon_after_it() -> None:
    state = advising()
    decide(GameEvent("danger_started", ts=50.0), state)
    assert decide(Tick(ts=FIRST_S * 3), state) == []
    decide(GameEvent("danger_ended", ts=FIRST_S * 3), state)
    assert decide(Tick(ts=FIRST_S * 3 + 1), state) == [GiveAdvice()]


def test_a_due_question_comes_before_a_tip_and_the_tip_waits_out_its_answer() -> None:
    state = DirectorState(
        question_gap_s=90.0,
        question_quiet_s=QUIET_S,
        advice_gap_s=GAP_S,
        advice_quiet_s=QUIET_S,
        advice_first_s=FIRST_S,
    )
    decide(OverlayConnected(display_scale=1.0, ts=0.0), state)
    state.last_question_at = FIRST_S - 90.0  # The next question falls due with the first tip.
    assert decide(Tick(ts=FIRST_S), state) == [AskQuestion()]
    assert decide(Tick(ts=FIRST_S + 5), state) == []
    assert decide(Tick(ts=FIRST_S + QUIET_S), state) == [GiveAdvice()]


def test_a_zero_gap_turns_every_tip_off() -> None:
    state = advising(gap_s=0)
    decide(learned(10.0, source="player"), state)
    for ts in (FIRST_S, 10_000.0, 20_000.0):
        assert decide(Tick(ts=ts), state) == []


@pytest.mark.parametrize(
    "fact",
    [
        learned(30.0),
        learned(30.0, subject="Playthrough", attribute="next milestone"),
        learned(30.0, subject="player", source="player", attribute="goal"),
    ],
    ids=["observed_progress", "any_playthrough_fact", "anything_the_player_said"],
)
def test_learning_where_the_player_stands_brings_a_tip_forward(fact: FactLearned) -> None:
    state = advising()
    assert decide(fact, state) == []
    assert decide(Tick(ts=30.0 + AFTER_LEARNING_S - 0.1), state) == []
    assert decide(Tick(ts=30.0 + AFTER_LEARNING_S), state) == [GiveAdvice()]


@pytest.mark.parametrize("source", ["observed", "wiki"])
def test_other_facts_leave_the_tip_where_it_was(source: str) -> None:
    state = advising()
    decide(learned(30.0, subject="player", source=source, attribute="class"), state)
    assert decide(Tick(ts=60.0), state) == []
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]


def test_learning_never_pushes_a_due_tip_later() -> None:
    state = advising()
    decide(learned(FIRST_S - 1.0), state)
    assert decide(Tick(ts=FIRST_S), state) == [GiveAdvice()]


def test_a_tip_brought_forward_still_waits_for_quiet_and_safety() -> None:
    state = advising()
    decide(PlayerSpeech(transcript="I just beat the first boss", ts=28.0), state)
    decide(learned(30.0, source="player"), state)
    decide(PartnerSpoke(ts=31.0), state)
    assert decide(Tick(ts=45.0), state) == []  # Due, but the partner only just spoke.
    decide(GameEvent("danger_started", ts=46.0), state)
    assert decide(Tick(ts=60.0), state) == []
    decide(GameEvent("danger_ended", ts=61.0), state)
    assert decide(Tick(ts=61.0), state) == [GiveAdvice()]


def test_after_a_tip_from_learning_the_next_waits_a_full_gap() -> None:
    state = advising()
    decide(learned(10.0), state)
    assert decide(Tick(ts=25.0), state) == [GiveAdvice()]
    assert decide(Tick(ts=25.0 + GAP_S - 0.1), state) == []
    assert decide(Tick(ts=25.0 + GAP_S), state) == [GiveAdvice()]
