"""The debug panel: what the brain hears, decides and does, shown with --debug-regions.

It gathers from three places so the busy modules barely change. The event bus has what speech
recognition hears and the player's mood. The director's hook gives each decision (why.py says
why). Latency, tools and how closely it's watching are already logged in fixed formats, which
scripts/latency_report.py reads too, so a log handler picks those up by their format strings.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from brain.director.rules import Action, DirectorState
from brain.director.why import explain
from brain.events import Event, EventBus, PlayerMood, PlayerSpeech, PlayerSpeechPartial
from shared.protocol import BrainMessage
from shared.protocol.messages import DebugBrain, DebugLatency

log = logging.getLogger(__name__)

SEND_EVERY_S = 0.5
# A tool's line stays this long after it starts, so a quick one is still readable.
DOING_SHOWN_S = 6.0
MAX_LATENCIES = 3
# The format strings these modules log with. A label of None takes the kind from the record.
_LATENCY = {
    "Latency: event to bark %.0f ms (%s)": "event → bark",
    "Latency: end of turn to first audio %.0f ms": "you stopped → voice",
    "Latency: player turn took %.0f ms": "turn, with tools",
}
_FRAME_LATENCY = "Latency: frame to %s %.0f ms"
_TOOL = "Tool %s: %s"
_FOCUS = "Watching the game at %s focus"
# How each tool reads on the panel, and which of its arguments to show.
_TOOLS = {
    "look_closer": ("looking closer", None),
    "look_back": ("looking back", None),
    "point_at": ("pointing", "target"),
    "lookup_wiki": ("wiki", "topic"),
    "read_open_page": ("reading the page", None),
    "think_hard": ("thinking hard", None),
    "watch_closely": ("watching closely", None),
    "remember_fact": ("remembering", "attribute"),
    "forget_fact": ("forgetting", "attribute"),
    "answer_question": ("noting your answer", None),
    "note_unknown": ("noting a question", None),
}


def tool_line(name: str, args: object) -> str:
    label, key = _TOOLS.get(name, (name.replace("_", " "), None))
    value = args.get(key) if key and isinstance(args, dict) else None
    return f"{label}: {value}" if isinstance(value, str) and value.strip() else label


class _Records(logging.Handler):
    """Hands the panel the records it shows. Matching the format string, not the text, so the
    numbers come straight from the record's arguments."""

    def __init__(self, panel: "BrainPanel") -> None:
        super().__init__(logging.INFO)
        self._panel = panel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._panel.note_record(str(record.msg), record.args or ())
        except Exception:
            self.handleError(record)


class BrainPanel:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hearing = ""
        self._live = False
        self._mood: str | None = None
        self._valence = 0.0
        self._decision: str | None = None
        self._doing: tuple[str, float] | None = None
        self._focus: str | None = None
        self._latency: dict[str, int] = {}  # Newest last
        self.handler = _Records(self)

    def note_decision(
        self, event: Event, actions: list[Action], busy: bool, state: DirectorState
    ) -> None:
        text = explain(event, actions, busy, state)
        if text is not None:
            self._decision = text

    def note_event(self, event: Event) -> None:
        match event:
            case PlayerSpeechPartial():
                self._hearing, self._live = event.transcript, True
            case PlayerSpeech():
                self._hearing, self._live = event.transcript, False
            case PlayerMood():
                self._mood, self._valence = event.label, max(-1.0, min(1.0, event.valence))

    def note_record(self, message: str, args: Sequence[Any] | Any) -> None:
        args = tuple(args) if isinstance(args, tuple) else ()
        if message in _LATENCY and args:
            self._add_latency(_LATENCY[message], args[0])
        elif message.startswith(_FRAME_LATENCY) and len(args) >= 2:
            self._add_latency(f"frame → {args[0]}", args[1])
        elif message == _TOOL and len(args) == 2:
            self._doing = (tool_line(str(args[0]), args[1]), self._clock())
        elif message == _FOCUS and args:
            self._focus = str(args[0])

    def _add_latency(self, label: str, ms: object) -> None:
        if isinstance(ms, int | float) and ms >= 0:
            self._latency.pop(label, None)
            self._latency[label] = round(ms)

    def snapshot(self) -> DebugBrain:
        doing = self._doing
        fresh = doing is not None and self._clock() - doing[1] <= DOING_SHOWN_S
        newest = list(self._latency.items())[::-1][:MAX_LATENCIES]
        return DebugBrain(
            hearing=self._hearing,
            hearing_live=self._live,
            mood=self._mood,
            mood_valence=self._valence,
            decision=self._decision,
            doing=doing[0] if fresh and doing else None,
            focus=self._focus,
            latency=[DebugLatency(label=label, ms=ms) for label, ms in newest],
        )

    async def run(self, bus: EventBus, send: Callable[[BrainMessage], Awaitable[None]]) -> None:
        events = bus.subscribe()
        brain_logger = logging.getLogger("brain")
        brain_logger.addHandler(self.handler)
        log.info("Showing what the brain hears and decides (--debug-regions)")
        try:
            while True:
                while not events.empty():
                    self.note_event(events.get_nowait())
                await send(self.snapshot())
                await asyncio.sleep(SEND_EVERY_S)
        finally:
            brain_logger.removeHandler(self.handler)
