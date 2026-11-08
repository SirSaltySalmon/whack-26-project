"""Decides when to speak. Pure and deterministic so every rule can be unit tested.

An LLM never decides this. Models only choose what to do inside a turn these rules started.

Questions and tips wait for a quiet stretch, measured from the player's last turn and the partner's
last spoken line. Game events don't count by themselves: the observer reports them all through
active play, so counting them meant the partner almost never found a moment to ask or advise. A
reaction to one counts once it's actually said, which the director reports with PartnerSpoke.

Paused (`Settings.paused`), nothing starts speech except a voice preview the player asked for.
Everything else still runs, so the partner keeps hearing, watching and taking notes. Questions stay
in memory's queue rather than being asked into silence, and the first tick after unpausing asks the
next one: unpausing is the player saying they're ready to talk again.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from brain.events import (
    Event,
    FactLearned,
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
    Tick,
    VoicePreviewRequested,
)

# Names the observer's tracker publishes. They describe any game, so this stays game-agnostic.
_DANGER_RISING = frozenset({"danger_started", "danger_high"})
_DANGER_OVER = "danger_ended"
# Learning about these is learning where the player stands, which is what grounds a tip. Memory
# files progress under "playthrough" for every game, so this is no game-specific knowledge.
_PROGRESS_SUBJECT = "playthrough"
_PLAYER_SOURCE = "player"


@dataclass(frozen=True)
class PartnerSpoke(Event):
    """The voice accepted one of the partner's lines. The director feeds this in itself.

    Kept off the bus like Tick: only the rules care, and every subscriber would have to skip it.
    """


@dataclass(frozen=True)
class Say:
    """Speak fixed text, such as a cached bark."""

    text: str


@dataclass(frozen=True)
class AskTalker:
    """Answer the player. Their turn replaces whatever the partner was about to say."""

    transcript: str
    # When they began speaking (monotonic), so tools can look at what they were seeing then.
    started_at: float | None = None


@dataclass(frozen=True)
class ReactToEvent:
    """Have the fast LLM comment on something seen in the game."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlayBark:
    """React with a pre-generated line, which skips the model and TTS."""

    kind: str  # A LineKind
    event: str  # The GameEvent name, for logs
    data: dict[str, Any]  # Passed on, in case there's no bark and it falls back
    # When the event happened, for the event-to-bark latency log. Not part of what was decided.
    ts: float | None = field(default=None, compare=False)


@dataclass(frozen=True)
class AskQuestion:
    """Ask the player the next open question, if memory has one."""


@dataclass(frozen=True)
class GiveAdvice:
    """Offer a short tip on what to do next. Skipped when the player turned hints off."""


@dataclass(frozen=True)
class CancelSpeech:
    """The player started talking, so drop any reply still being prepared."""


@dataclass(frozen=True)
class StopSpeaking:
    """The player paused the partner. Unlike CancelSpeech, this also stops a turn running a tool."""


@dataclass(frozen=True)
class SetVoice:
    voice_id: str | None


Action = (
    Say
    | AskTalker
    | ReactToEvent
    | PlayBark
    | AskQuestion
    | GiveAdvice
    | CancelSpeech
    | StopSpeaking
    | SetVoice
)


@dataclass
class DirectorState:
    bark_cooldown_s: float = 8.0
    question_gap_s: float = 90.0
    question_quiet_s: float = 20.0
    last_bark_at: float | None = None
    last_question_at: float | None = None
    # Tips get old faster than curiosity does, so they're rarer than questions. A 0 gap turns them
    # off. The first comes sooner than the gap, and sooner again once the partner learns where the
    # player stands, because that's when a tip can be about their game rather than generic.
    advice_gap_s: float = 180.0
    advice_quiet_s: float = 20.0
    advice_first_s: float = 90.0
    advice_after_learning_s: float = 15.0
    # When the next tip is due. None until the overlay connects.
    next_advice_at: float | None = None
    # The player's last turn or the partner's last spoken line. Connecting sets it too, so nothing
    # is asked the moment the player arrives. Assigned rather than maxed, so it follows the latest.
    last_talk_at: float | None = None
    turn_started_at: float | None = None
    in_danger: bool = False
    # Also means the overlay has connected, so nothing is asked with no one there to answer it.
    greeted: bool = False
    # GameEvent name -> LineKind. Events not listed here go to the talker.
    bark_events: Mapping[str, str] = field(default_factory=dict)
    paused: bool = False
    # Set by unpausing, and cleared once a question is asked.
    ask_on_resume: bool = False


def _quiet(ts: float, state: DirectorState, needed_s: float) -> bool:
    if not state.greeted or state.in_danger:
        return False
    return state.last_talk_at is None or ts - state.last_talk_at >= needed_s


def _may_ask(ts: float, state: DirectorState) -> bool:
    if state.ask_on_resume:
        # No quiet stretch or gap needed: the player just asked it to talk again. Danger still
        # waits, since a question then would distract them.
        return state.greeted and not state.in_danger
    if not _quiet(ts, state, state.question_quiet_s):
        return False
    return state.last_question_at is None or ts - state.last_question_at >= state.question_gap_s


def _may_advise(ts: float, state: DirectorState) -> bool:
    due = state.next_advice_at
    if state.advice_gap_s <= 0 or due is None or ts < due:
        return False
    if not _quiet(ts, state, state.advice_quiet_s):
        return False
    # Right after a question, a tip would talk over the player's answer.
    asked = state.last_question_at
    return asked is None or ts - asked >= state.advice_quiet_s


def _learned_where_they_stand(event: FactLearned) -> bool:
    return event.subject.casefold() == _PROGRESS_SUBJECT or event.source == _PLAYER_SOURCE


def decide(event: Event, state: DirectorState) -> list[Action]:
    """The hints setting isn't an input: it changes what the partner says, not when it talks."""
    match event:
        case OverlayConnected():
            state.last_talk_at = event.ts
            # The overlay can reconnect during a session, and that shouldn't greet again.
            if state.greeted:
                return []
            state.greeted = True
            state.next_advice_at = event.ts + state.advice_first_s
            return [] if state.paused else [Say("Brain connected.")]
        case PlayerStartedSpeaking():
            state.last_talk_at = event.ts
            state.turn_started_at = event.ts
            return [CancelSpeech()]
        case PlayerSpeech():
            state.last_talk_at = event.ts
            started_at, state.turn_started_at = state.turn_started_at, None
            if state.paused:
                # Heard and noted by memory, which reads the bus itself, but not answered.
                return []
            return [AskTalker(event.transcript, started_at)]
        case PartnerSpoke():
            state.last_talk_at = event.ts
            return []
        case FactLearned():
            if state.next_advice_at is not None and _learned_where_they_stand(event):
                # Only ever sooner: learning something must not push back a tip already due.
                soon = event.ts + state.advice_after_learning_s
                state.next_advice_at = min(state.next_advice_at, soon)
            return []
        case GameEvent():
            if event.name in _DANGER_RISING:
                state.in_danger = True
            elif event.name == _DANGER_OVER:
                state.in_danger = False
            if state.paused:
                return []
            cooling = (
                state.last_bark_at is not None
                and event.ts - state.last_bark_at < state.bark_cooldown_s
            )
            if cooling:
                return []
            state.last_bark_at = event.ts
            kind = state.bark_events.get(event.name)
            if kind is not None:
                return [PlayBark(kind, event.name, event.data, ts=event.ts)]
            return [ReactToEvent(event.name, event.data)]
        case Tick():
            if state.paused:
                return []
            # Questions first: an answer makes the next tip better.
            if _may_ask(event.ts, state):
                state.last_question_at = event.ts
                state.ask_on_resume = False
                return [AskQuestion()]
            if _may_advise(event.ts, state):
                state.next_advice_at = event.ts + state.advice_gap_s
                return [GiveAdvice()]
            return []
        case SettingsChanged():
            # Sending the current voice again is harmless, so this needs no change tracking.
            actions: list[Action] = [SetVoice(getattr(event.settings, "voice_id", None))]
            paused = bool(getattr(event.settings, "paused", False))
            if paused and not state.paused:
                actions.append(StopSpeaking())
            elif state.paused and not paused:
                state.ask_on_resume = True
            state.paused = paused
            return actions
        case VoicePreviewRequested():
            # A plain Say, so it's skipped while the partner is talking and never interrupts.
            return [Say(event.text)]
        case _:
            return []
