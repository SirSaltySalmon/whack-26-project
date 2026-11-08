"""Decides when to speak. Pure and deterministic so every rule can be unit tested.

An LLM never decides this. Models only choose what to do inside a turn these rules started.

A turn that only acknowledges, such as "okay" or "thanks", isn't answered unless the partner's
last line asked something or the player's previous turn is still waiting for a reply (acks.py).

Tips, and questions if the player's pacing asks for it, wait for a quiet stretch, measured from
the player's last turn and the partner's last spoken line. Game events don't count by themselves:
the observer reports them all through active play, so counting them meant the partner almost never
found a moment to ask or advise. A reaction counts once it's actually said, which the director
reports with PartnerSpoke.

Paused (`Settings.paused`), nothing starts speech except a voice preview the player asked for.
Everything else still runs, so the partner keeps hearing, watching and taking notes. Questions stay
in memory's queue rather than being asked into silence, and the first tick after unpausing asks the
next one: unpausing is the player saying they're ready to talk again.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from brain.director.acks import only_acknowledges

# Re-exported, so modules that import actions from here keep working.
from brain.director.actions import (
    Action,
    AskQuestion,
    AskTalker,
    CancelSpeech,
    GiveAdvice,
    PlayBark,
    ReactToEvent,
    Say,
    SetVoice,
    StopSpeaking,
)
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

    # The line asked something, so the player's "okay" may be their answer.
    asked: bool = False


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
    paused: bool = False
    # The player turned the partner's vision off, so a tip can't point.
    blind: bool = False
    # Set by unpausing, and cleared once a question is asked.
    ask_on_resume: bool = False
    # A player turn nothing has been said for yet, and whether the partner's last line asked
    # something. Either means a bare "okay" may still need answering (acks.py).
    answering: bool = False
    partner_asked: bool = False


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
            if only_acknowledges(event.transcript) and not (state.answering or state.partner_asked):
                # A teammate lets "okay" or "thanks" be. Memory still hears it from the bus.
                return []
            state.answering = True
            return [AskTalker(event.transcript, started_at)]
        case PartnerSpoke():
            state.last_talk_at = event.ts
            state.answering = False
            state.partner_asked = event.asked
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
            origin = Origin.of(event)
            if kind is not None:
                return [PlayBark(kind, event.name, event.data, ts=event.ts, origin=origin)]
            return [ReactToEvent(event.name, event.data, origin=origin)]
        case Tick():
            if state.paused:
                return []
            # Questions first: an answer makes the next tip better.
            if _may_ask(event.ts, state):
                state.last_question_at = event.ts
                state.ask_on_resume = False
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
            actions: list[Action] = [SetVoice(getattr(event.settings, "voice_id", None))]
            paused = bool(getattr(event.settings, "paused", False))
            if paused and not state.paused:
                actions.append(StopSpeaking())
            elif state.paused and not paused:
                state.ask_on_resume = True
            state.paused = paused
            state.blind = not getattr(event.settings, "vision_enabled", True)
            if state.blind:
                # Blind, it can't know a fight is still on, so it stops holding back for one.
                state.in_danger = False
            return actions
        case VoicePreviewRequested():
            # A plain Say, so it's skipped while the partner is talking and never interrupts.
            return [Say(event.text)]
        case _:
            return []
