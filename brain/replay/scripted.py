"""Plays the partner's recorded lines back as the talker, so a replay needs no network or keys."""

import logging
from collections import Counter, deque
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from brain.llm.base import ChatTurn, LLMUnavailableError, System
from brain.replay.format import (
    EVENTS,
    MESSAGES,
    PARTNER_SAID,
    EventRecord,
    MessageRecord,
    read_jsonl,
)

log = logging.getLogger(__name__)


class ScriptedTalker:
    """A TextLLM that returns the recorded partner lines in order, so replay needs no network.

    Lines go by order, not by prompt, so a change to the director's rules can shift which line
    answers what. Running out raises LLMUnavailableError, which the talker treats as staying quiet.
    """

    def __init__(self, lines: Sequence[str]) -> None:
        self._lines = deque(lines)

    @property
    def remaining(self) -> int:
        return len(self._lines)

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        if not self._lines:
            raise LLMUnavailableError("No more recorded lines")
        yield self._lines.popleft()


def partner_lines(session: Path) -> list[str]:
    """The partner's recorded lines in order, minus the ones that were questions.

    The director speaks questions from memory without the talker, so leaving their text in would
    shift every later reply by one. Blocking disk reads, so call it from a worker thread.
    """
    if not (session / EVENTS).is_file():
        log.warning("No %s in %s, so the replay talker has nothing to say", EVENTS, session)
        return []
    try:
        events = read_jsonl(session / EVENTS, EventRecord)
        messages = read_jsonl(session / MESSAGES, MessageRecord)
    except (OSError, ValueError) as exc:
        log.error("Can't read the partner's lines from %s (%s)", session, exc)
        return []

    # A multiset, so a question asked once removes its text once, even if a reply says it again.
    asked = Counter(
        record.message.get("text")
        for record in messages
        if record.message.get("type") == "question.ask"
    )
    lines: list[str] = []
    for record in events:
        if record.kind != PARTNER_SAID:
            continue
        text = record.data.get("text")
        if not isinstance(text, str):
            log.warning("Skipping a recorded partner line with no text: %.200s", record.data)
            continue
        if asked[text] > 0:
            asked[text] -= 1
            continue
        lines.append(text)
    left_out = sum(1 for r in events if r.kind == PARTNER_SAID) - len(lines)
    log.info("Replay talker has %d recorded lines (%d left out)", len(lines), left_out)
    return lines
