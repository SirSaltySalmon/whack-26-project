from collections.abc import Mapping

import pytest

from brain.director.rules import (
    AskQuestion,
    AskTalker,
    CancelSpeech,
    DirectorState,
    PartnerSpoke,
    PlayBark,
    ReactToEvent,
    Say,
    SetVoice,
    decide,
)
from brain.events import (
    Event,
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
    Tick,
)
from shared.protocol.messages import Settings

QUIET_S = 20.0
GAP_S = 90.0
BARKS = {"danger_started": "danger", "danger_high": "danger_high", "player_died": "died"}


def connected(at: float = 0.0, bark_events: Mapping[str, str] | None = None) -> DirectorState:
    """Every condition for asking holds here, once QUIET_S has passed since `at`.

    Tips are off, so only the question rules are in play. test_advice.py has the tip rules.
    """
    state = DirectorState(
        question_quiet_s=QUIET_S,
        question_gap_s=GAP_S,
        advice_gap_s=0,
        bark_events=bark_events or {},
    )
    decide(OverlayConnected(display_scale=1.0, ts=at), state)
    return state


def test_overlay_connection_is_announced() -> None:
    assert decide(OverlayConnected(display_scale=1.0), DirectorState()) == [Say("Brain connected.")]


def test_reconnecting_the_overlay_doesnt_greet_again() -> None:
    state = DirectorState()
    assert decide(OverlayConnected(display_scale=1.0, ts=1.0), state) == [Say("Brain connected.")]
    assert decide(OverlayConnected(display_scale=1.0, ts=2.0), state) == []


def test_player_speech_is_answered() -> None:
    event = PlayerSpeech(transcript="what's that?")
    assert decide(event, DirectorState()) == [AskTalker("what's that?")]


def test_start_of_turn_cancels_speech_and_the_next_speech_carries_its_start() -> None:
    state = DirectorState()
    assert decide(PlayerStartedSpeaking(ts=5.0), state) == [CancelSpeech()]
    event = PlayerSpeech(transcript="what's that?", ts=7.0)
    assert decide(event, state) == [AskTalker("what's that?", 5.0)]


def test_a_start_of_turn_only_belongs_to_the_speech_after_it() -> None:
    state = DirectorState()
    decide(PlayerStartedSpeaking(ts=5.0), state)
    decide(PlayerSpeech(transcript="first", ts=7.0), state)
    assert decide(PlayerSpeech(transcript="second", ts=9.0), state) == [AskTalker("second", None)]


def test_a_turn_that_restarts_uses_the_latest_start() -> None:
    state = DirectorState()
    decide(PlayerStartedSpeaking(ts=5.0), state)
    decide(PlayerStartedSpeaking(ts=6.0), state)
    assert decide(PlayerSpeech(transcript="hi", ts=7.0), state) == [AskTalker("hi", 6.0)]


def test_game_events_go_to_the_talker_with_their_details() -> None:
    event = GameEvent("danger_started", {"level": "high"}, ts=1.0)
    assert decide(event, DirectorState()) == [ReactToEvent("danger_started", {"level": "high"})]


def test_barks_respect_the_cooldown() -> None:
    state = DirectorState(bark_cooldown_s=8.0)
    assert decide(GameEvent("death", ts=10.0), state)
    assert decide(GameEvent("death", ts=15.0), state) == []
    assert decide(GameEvent("death", ts=18.0), state)


def test_tick_asks_after_exactly_the_quiet_stretch() -> None:
    assert decide(Tick(ts=QUIET_S), connected()) == [AskQuestion()]


def test_tick_never_asks_with_no_overlay_connected() -> None:
    state = DirectorState(question_quiet_s=QUIET_S, question_gap_s=GAP_S)
    assert decide(Tick(ts=10_000.0), state) == []


def test_tick_waits_out_the_quiet_stretch_and_waiting_spends_no_budget() -> None:
    state = connected()
    assert decide(Tick(ts=QUIET_S - 0.1), state) == []
    assert decide(Tick(ts=QUIET_S), state) == [AskQuestion()]


@pytest.mark.parametrize(
    "talk",
    [
        PlayerStartedSpeaking(ts=50.0),
        PlayerSpeech(transcript="hi", ts=50.0),
        PartnerSpoke(ts=50.0),
        OverlayConnected(display_scale=1.0, ts=50.0),
    ],
    ids=["start_of_turn", "speech", "partner_line", "reconnect"],
)
def test_talk_restarts_the_quiet_stretch(talk: Event) -> None:
    state = connected()
    decide(talk, state)
    assert decide(Tick(ts=50.0 + QUIET_S - 0.1), state) == []
    assert decide(Tick(ts=50.0 + QUIET_S), state) == [AskQuestion()]


@pytest.mark.parametrize("name", ["something", "health_low", "player_died", "danger_ended"])
def test_a_game_event_alone_doesnt_restart_the_quiet_stretch(name: str) -> None:
    # The observer reports events all through active play, so counting them meant never asking.
    state = connected(bark_events=BARKS)
    assert decide(GameEvent(name, ts=50.0), state)  # The partner would react...
    # ...but until that reaction is actually said, it's still quiet.
    assert decide(Tick(ts=QUIET_S + 35.0), state) == [AskQuestion()]


def test_events_every_few_seconds_still_leave_room_for_a_question() -> None:
    state = connected()
    for ts in range(1, 60, 3):
        decide(GameEvent("something", ts=float(ts)), state)
    assert decide(Tick(ts=60.0), state) == [AskQuestion()]


def test_tick_waits_out_the_gap_since_the_last_question() -> None:
    state = connected()
    asked_at = QUIET_S + 5.0
    assert decide(Tick(ts=asked_at), state) == [AskQuestion()]
    assert decide(Tick(ts=asked_at + GAP_S - 0.1), state) == []
    assert decide(Tick(ts=asked_at + GAP_S), state) == [AskQuestion()]


@pytest.mark.parametrize("name", ["danger_started", "danger_high"])
def test_tick_never_asks_during_danger_and_asks_again_after_it(name: str) -> None:
    state = connected()
    decide(GameEvent(name, ts=0.0), state)
    assert decide(Tick(ts=10_000.0), state) == []
    decide(GameEvent("danger_ended", ts=10_000.0), state)
    assert decide(Tick(ts=10_000.0 + QUIET_S), state) == [AskQuestion()]


def test_game_events_and_ticks_act_the_same_with_hints_on_or_off() -> None:
    script: tuple[Event, ...] = (
        OverlayConnected(display_scale=1.0, ts=0.0),
        GameEvent("danger_started", {"level": "high"}, ts=1.0),
        GameEvent("danger_high", ts=2.0),
        Tick(ts=500.0),
        GameEvent("danger_ended", ts=600.0),
        Tick(ts=700.0),
        Tick(ts=701.0),
        GameEvent("boss_visible", ts=800.0),
    )

    def decisions(proactive: bool) -> list[list[object]]:
        state = DirectorState()
        decide(SettingsChanged(settings=Settings(proactive=proactive)), state)
        return [list(decide(event, state)) for event in script]

    with_hints, without_hints = decisions(True), decisions(False)
    assert with_hints == without_hints
    # Equal could also mean silent both ways, which is exactly what hints off must not be.
    assert [ReactToEvent("danger_started", {"level": "high"})] in without_hints
    assert [ReactToEvent("boss_visible", {})] in without_hints
    assert [AskQuestion()] in without_hints


@pytest.mark.parametrize("name", ["danger_started", "danger_high"])
def test_danger_rises_and_ends_with_its_events(name: str) -> None:
    state = DirectorState()
    decide(GameEvent(name, ts=0.0), state)
    assert state.in_danger
    decide(GameEvent("danger_ended", ts=100.0), state)
    assert not state.in_danger


def test_danger_still_starts_when_the_cooldown_swallows_the_event() -> None:
    state = connected()
    assert decide(GameEvent("something", ts=10.0), state)
    assert decide(GameEvent("danger_started", ts=11.0), state) == []
    assert state.in_danger
    assert decide(Tick(ts=1000.0), state) == []


def test_danger_still_ends_when_the_cooldown_swallows_the_event() -> None:
    state = connected()
    assert decide(GameEvent("danger_started", ts=10.0), state)
    assert decide(GameEvent("danger_ended", ts=11.0), state) == []
    assert not state.in_danger
    assert decide(Tick(ts=10.0 + QUIET_S), state) == [AskQuestion()]


def test_other_events_leave_danger_as_it_was() -> None:
    state = DirectorState()
    decide(GameEvent("danger_started", ts=0.0), state)
    decide(GameEvent("health_low", ts=100.0), state)
    assert state.in_danger


@pytest.mark.parametrize("voice_id", ["voice-2", None])
def test_changing_settings_sets_the_voice(voice_id: str | None) -> None:
    event = SettingsChanged(settings=Settings(voice_id=voice_id))
    assert decide(event, DirectorState()) == [SetVoice(voice_id)]


def test_a_mapped_event_plays_its_bark_and_passes_on_its_details() -> None:
    event = GameEvent("player_died", {"where": "cave"}, ts=1.0)
    state = DirectorState(bark_events=BARKS)
    assert decide(event, state) == [PlayBark("died", "player_died", {"where": "cave"})]


def test_an_unmapped_event_still_goes_to_the_talker() -> None:
    event = GameEvent("boss_visible", {"value": 1}, ts=1.0)
    state = DirectorState(bark_events=BARKS)
    assert decide(event, state) == [ReactToEvent("boss_visible", {"value": 1})]


@pytest.mark.parametrize("name", sorted(BARKS))
def test_an_empty_map_sends_every_event_to_the_talker(name: str) -> None:
    assert decide(GameEvent(name, ts=1.0), DirectorState()) == [ReactToEvent(name, {})]


def test_barks_and_reactions_share_one_cooldown() -> None:
    state = DirectorState(bark_cooldown_s=8.0, bark_events=BARKS)
    assert decide(GameEvent("player_died", ts=10.0), state)
    assert decide(GameEvent("player_died", ts=15.0), state) == []
    assert decide(GameEvent("boss_visible", ts=17.0), state) == []
    assert decide(GameEvent("player_died", ts=18.0), state) == [PlayBark("died", "player_died", {})]
    assert decide(GameEvent("boss_visible", ts=25.0), state) == []
    assert decide(GameEvent("boss_visible", ts=26.0), state) == [ReactToEvent("boss_visible", {})]


def test_a_mapped_danger_event_still_raises_danger() -> None:
    state = DirectorState(bark_events=BARKS)
    actions = decide(GameEvent("danger_started", ts=1.0), state)
    assert actions == [PlayBark("danger", "danger_started", {})]
    assert state.in_danger


def test_a_mapped_danger_event_still_raises_danger_during_the_cooldown() -> None:
    state = DirectorState(bark_cooldown_s=8.0, bark_events=BARKS)
    assert decide(GameEvent("player_died", ts=1.0), state)
    assert decide(GameEvent("danger_high", ts=2.0), state) == []
    assert state.in_danger


def test_a_mapped_end_of_danger_still_ends_it() -> None:
    state = DirectorState(bark_events={"danger_ended": "danger"})
    decide(GameEvent("danger_started", ts=1.0), state)
    actions = decide(GameEvent("danger_ended", ts=100.0), state)
    assert actions == [PlayBark("danger", "danger_ended", {})]
    assert not state.in_danger


def test_a_bark_restarts_the_quiet_stretch_once_its_said() -> None:
    state = connected(bark_events=BARKS)
    decide(GameEvent("player_died", ts=50.0), state)
    decide(PartnerSpoke(ts=50.5), state)
    assert decide(Tick(ts=50.5 + QUIET_S - 0.1), state) == []
    assert decide(Tick(ts=50.5 + QUIET_S), state) == [AskQuestion()]


def test_talk_before_the_overlay_connects_doesnt_let_it_ask() -> None:
    state = DirectorState(question_quiet_s=QUIET_S, question_gap_s=GAP_S)
    decide(PlayerSpeech(transcript="hi", ts=0.0), state)
    decide(PartnerSpoke(ts=1.0), state)
    assert decide(Tick(ts=10_000.0), state) == []


def test_a_partner_line_decides_nothing_by_itself() -> None:
    assert decide(PartnerSpoke(ts=1.0), connected()) == []
