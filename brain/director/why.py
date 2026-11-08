"""Says in a few words what the director just decided and why, for the debug panel.

Pure, so it's tested like the rules: given the event, what the rules returned, whether the speech
slot was busy and the state the rules left, it explains. None means there's nothing worth showing,
such as a tick that decided nothing, which comes every few seconds.
"""

from collections.abc import Callable, Sequence

from brain.director.rules import (
    Action,
    AskQuestion,
    AskTalker,
    DirectorState,
    GiveAdvice,
    PlayBark,
    ReactToEvent,
    Say,
    StopSpeaking,
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

# Told each decision, whether the speech slot was busy, and the state the rules left.
DecisionHook = Callable[[Event, list[Action], bool, DirectorState], None]

# Actions that wait for an empty slot. A player turn and cancelling never do.
_SLOT_ACTIONS = (Say, PlayBark, ReactToEvent, AskQuestion, GiveAdvice)


def ignore_decision(
    _event: Event, _actions: list[Action], _busy: bool, _state: DirectorState
) -> None:
    return None


def explain(
    event: Event, actions: Sequence[Action], busy: bool, state: DirectorState
) -> str | None:
    kinds = {type(action) for action in actions}
    skipped = busy and any(isinstance(action, _SLOT_ACTIONS) for action in actions)
    match event:
        case PlayerStartedSpeaking():
            return "listening: stopped talking" if busy else "listening"
        case PlayerSpeech():
            return "answering you" if AskTalker in kinds else "heard you, but paused"
        case GameEvent():
            name = event.name.replace("_", " ")
            if skipped:
                return f"{name}: skipped, already talking"
            if PlayBark in kinds:
                return f"{name}: quick line"
            if ReactToEvent in kinds:
                return f"{name}: reacting"
            return f"{name}: quiet, paused" if state.paused else f"{name}: quiet, cooling down"
        case Tick():
            if AskQuestion in kinds:
                return "asking you a question"
            if GiveAdvice in kinds:
                return "offering a tip"
            return None
        case OverlayConnected():
            return "greeting" if Say in kinds else None
        case SettingsChanged():
            if StopSpeaking in kinds:
                return "paused by you"
            return None
        case _:
            return None
