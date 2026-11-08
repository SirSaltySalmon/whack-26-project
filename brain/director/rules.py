"""Decides when to speak. Pure and deterministic so every rule can be unit tested.

An LLM never decides this. Models only choose what to do inside a turn these rules started.

Tips, and questions if the player's pacing asks for it, wait for a quiet stretch, measured from
the player's last turn and the partner's last spoken line. Game events don't count by themselves:
the observer reports them all through active play, so counting them meant the partner almost never
found a moment to ask or advise. A reaction counts once it's actually said, which the director
reports with PartnerSpoke.
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
from brain.latency import Origin
from shared.protocol.messages import Pacing

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
    # Where it was first seen, for the frame-to-voice latency log. Not part of what was decided.
    origin: Origin | None = field(default=None, compare=False)


@dataclass(frozen=True)
class PlayBark:
    """React with a pre-generated line, which skips the model and TTS."""

    kind: str  # A LineKind
    event: str  # The GameEvent name, for logs
    data: dict[str, Any]  # Passed on, in case there's no bark and it falls back
    # When the event happened, for the event-to-bark latency log. Not part of what was decided.
    ts: float | None = field(default=None, compare=False)
    origin: Origin | None = field(default=None, compare=False)


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
class SetVoice:
    voice_id: str | None


Action = (
    Say | AskTalker | ReactToEvent | PlayBark | AskQuestion | GiveAdvice | CancelSpeech | SetVoice
)


_PACING = Pacing()


@dataclass
class DirectorState:
    # The gaps and quiet stretches default to the player's pacing settings, which replace them
    # whenever settings change.
    bark_cooldown_s: float = _PACING.event_gap_s
    question_gap_s: float = _PACING.question_gap_s
    question_quiet_s: float = _PACING.question_quiet_s
    last_bark_at: float | None = None
    last_question_at: float | None = None
    # Tips get old faster than curiosity does, so they're rarer than questions. A 0 gap turns them
    # off. The first comes sooner than the gap, and sooner again once the partner learns where the
    # player stands, because that's when a tip can be about their game rather than generic.
    advice_gap_s: float = _PACING.advice_gap_s
    advice_quiet_s: float = _PACING.advice_quiet_s
    advice_first_s: float = _PACING.advice_first_s
    advice_after_learning_s: float = 15.0
    # When the next tip is due. None until the overlay connects.
    next_advice_at: float | None = None
    last_advice_at: float | None = None
    # The player's last turn or the partner's last spoken line. Connecting sets it too, so nothing
    # is asked the moment the player arrives. Assigned rather than maxed, so it follows the latest.
    last_talk_at: float | None = None
    turn_started_at: float | None = None
    in_danger: bool = False
    # Also means the overlay has connected, so nothing is asked with no one there to answer it.
    greeted: bool = False
    # GameEvent name -> LineKind. Events not listed here go to the talker.
    bark_events: Mapping[str, str] = field(default_factory=dict)


def _quiet(ts: float, state: DirectorState, needed_s: float) -> bool:
    if not state.greeted or state.in_danger:
        return False
    return state.last_talk_at is None or ts - state.last_talk_at >= needed_s


def _may_ask(ts: float, state: DirectorState) -> bool:
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


def apply_pacing(state: DirectorState, pacing: Pacing, ts: float | None = None) -> None:
    """Takes the player's pacing settings. With `ts`, a tip already scheduled further out than
    the new timing allows is brought forward, so a shorter gap is felt now rather than after the
    old one. A longer gap leaves it be: like learning, a change only ever makes a tip sooner."""
    state.bark_cooldown_s = pacing.event_gap_s
    state.question_gap_s = pacing.question_gap_s
    state.question_quiet_s = pacing.question_quiet_s
    state.advice_gap_s = pacing.advice_gap_s
    state.advice_quiet_s = pacing.advice_quiet_s
    state.advice_first_s = pacing.advice_first_s
    if ts is None or state.next_advice_at is None or pacing.advice_gap_s <= 0:
        return
    wait = pacing.advice_first_s if state.last_advice_at is None else pacing.advice_gap_s
    state.next_advice_at = min(state.next_advice_at, ts + wait)


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
            return [Say("Brain connected.")]
        case PlayerStartedSpeaking():
            state.last_talk_at = event.ts
            state.turn_started_at = event.ts
            return [CancelSpeech()]
        case PlayerSpeech():
            state.last_talk_at = event.ts
            started_at, state.turn_started_at = state.turn_started_at, None
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
            cooling = (
                state.last_bark_at is not None
                and event.ts - state.last_bark_at < state.bark_cooldown_s
            )
            if cooling:
                return []
            state.last_bark_at = event.ts
            kind = state.bark_events.get(event.name)
            origin = Origin.of(event)
            if kind is not None:
                return [PlayBark(kind, event.name, event.data, ts=event.ts, origin=origin)]
            return [ReactToEvent(event.name, event.data, origin=origin)]
        case Tick():
            # Questions first: an answer makes the next tip better.
            if _may_ask(event.ts, state):
                state.last_question_at = event.ts
                return [AskQuestion()]
            if _may_advise(event.ts, state):
                state.last_advice_at = event.ts
                state.next_advice_at = event.ts + state.advice_gap_s
                return [GiveAdvice()]
            return []
        case SettingsChanged():
            pacing = getattr(event.settings, "pacing", None)
            if isinstance(pacing, Pacing):
                apply_pacing(state, pacing, event.ts)
            # Sending the current voice again is harmless, so this needs no change tracking.
            return [SetVoice(getattr(event.settings, "voice_id", None))]
        case VoicePreviewRequested():
            # A plain Say, so it's skipped while the partner is talking and never interrupts.
            return [Say(event.text)]
        case _:
            return []
