from brain.director.rules import AskTalker, DirectorState, Say, decide
from brain.events import GameEvent, OverlayConnected, PlayerSpeech


def test_overlay_connection_is_announced() -> None:
    assert decide(OverlayConnected(display_scale=1.0), DirectorState(), True) == [
        Say("Brain connected.")
    ]


def test_player_speech_is_answered_even_when_not_proactive() -> None:
    event = PlayerSpeech(transcript="what's that?")
    assert decide(event, DirectorState(), False) == [AskTalker("what's that?")]


def test_game_events_stay_quiet_when_not_proactive() -> None:
    assert decide(GameEvent("death", ts=1.0), DirectorState(), False) == []


def test_barks_respect_the_cooldown() -> None:
    state = DirectorState(bark_cooldown_s=8.0)
    assert decide(GameEvent("death", ts=10.0), state, True)
    assert decide(GameEvent("death", ts=15.0), state, True) == []
    assert decide(GameEvent("death", ts=18.0), state, True)
