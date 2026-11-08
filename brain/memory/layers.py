"""Lays out what a reply knows in three layers, each with its own budget (docs/CONTEXT_PLAN.md).

- MEMORY goes in the system prompt after the rules, and is cached: it changes a few times a
  session. GAME, SESSION, LAST TIME, PLAYER and UNSURE.
- The conversation goes in as messages, cached up to the last one, since it only grows at its end.
- LIVE opens the latest message and changes every call. TIME, NOW, RECALL and ASKED, plus what the
  director adds with `with_live`, such as the open wiki page.

Stable things first and what's happening now last, next to their words, where the model uses
information best.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

from brain.llm.base import ChatTurn
from brain.memory.context import (
    DEFAULT_LIMITS,
    LIVE_END,
    LIVE_HEADER,
    MEMORY_HEADER,
    ContextInputs,
    ContextLimits,
    clean,
    format_asked,
    format_fact,
    shorten,
    shrink_or_drop,
    take_within,
)
from brain.memory.conversation import history_turns, session_clock

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TalkerContext:
    """What one reply knows: `memory` for the system prompt, the earlier conversation as
    `history`, and `live` to open the latest message."""

    memory: str = ""
    history: tuple[ChatTurn, ...] = ()
    live: str = ""

    def with_live(self, label: str, text: str) -> "TalkerContext":
        """Adds a `LABEL: text` section to LIVE, such as the partner's own state or the page."""
        # A line reading as LIVE's end would let page text pose as what the player said.
        body = "\n".join(line for line in text.splitlines() if line.strip() != LIVE_END)
        section = f"{label}: {body}"
        return replace(self, live=f"{self.live}\n{section}" if self.live else section)

    def memory_block(self) -> str:
        return f"{MEMORY_HEADER}\n{self.memory}" if self.memory else ""

    def message(self, words: str) -> str:
        """The latest message: LIVE, then their words, or why the partner is speaking now."""
        if not self.live:
            return words
        return f"{LIVE_HEADER}\n{self.live}\n{LIVE_END}\n\n{words}"

    def render(self) -> str:
        """Everything the model gets as one string, for the Control Center's preview."""
        lines: list[str] = []
        if self.memory:
            lines += [MEMORY_HEADER, self.memory]
        if self.history:
            lines.append("CONVERSATION:")
            lines += [
                f"{'partner' if turn.role == 'assistant' else 'player'}: {turn.text}"
                for turn in self.history
            ]
        if self.live:
            lines += [LIVE_HEADER, self.live]
        return "\n".join(lines)


# What the director and think_hard ask for: the words to recall by, and the words being answered
# (None for game events, tips and think_hard).
ContextSource = Callable[[str, str | None], Awaitable[TalkerContext]]


def _sections(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}: {body}" for label, body in pairs if body)


@dataclass
class _Memory:
    game: str
    session: str
    last_time: str
    player: list[str] = field(default_factory=list)
    unsure: list[str] = field(default_factory=list)

    def render(self) -> str:
        return _sections(
            [
                ("GAME", self.game),
                ("SESSION", self.session),
                ("LAST TIME", self.last_time),
                ("PLAYER", "; ".join(self.player)),
                ("UNSURE", "; ".join(self.unsure)),
            ]
        )

    def excess(self, cap: int) -> int:
        return len(self.render()) - cap

    def fit(self, cap: int) -> str:
        """Least needed first. Guesses sit after the player's own facts, so they go first."""
        if self.excess(cap) > 0:
            log.warning("MEMORY is %d characters over its budget; trimming", self.excess(cap))
        self.last_time = shrink_or_drop(self.last_time, self.excess(cap))
        while self.unsure and self.excess(cap) > 0:
            self.unsure.pop()
        while self.player and self.excess(cap) > 0:
            self.player.pop()
        self.session = shrink_or_drop(self.session, self.excess(cap))
        self.game = shorten(self.game, len(self.game) - max(self.excess(cap), 0))
        # Only reachable with a cap too small for the labels themselves. It still has to hold.
        return self.render()[: max(cap, 0)]


@dataclass
class _Live:
    time: str
    now: str
    asked: str
    recalled: list[str] = field(default_factory=list)

    def render(self) -> str:
        # ASKED comes last, right above their words, which probably answer it.
        return _sections(
            [
                ("TIME", self.time),
                ("NOW", self.now),
                ("RECALL", "; ".join(self.recalled)),
                ("ASKED", self.asked),
            ]
        )

    def excess(self, cap: int) -> int:
        return len(self.render()) - cap

    def fit(self, cap: int) -> str:
        if self.excess(cap) > 0:
            log.warning("LIVE is %d characters over its budget; trimming", self.excess(cap))
        while self.recalled and self.excess(cap) > 0:
            self.recalled.pop()
        self.asked = shrink_or_drop(self.asked, self.excess(cap))
        self.now = shorten(self.now, len(self.now) - max(self.excess(cap), 0))
        return self.render()[: max(cap, 0)]


def _memory(inputs: ContextInputs, limits: ContextLimits) -> str:
    game, brief = clean(inputs.game), clean(inputs.brief)
    facts = [
        shorten(format_fact(fact, limits.fact_chars), limits.fact_chars)
        for fact in inputs.facts[: limits.max_facts]
        if clean(fact.value)
    ]
    unsure = [clean(text) for text in inputs.unsure[: limits.max_unsure] if clean(text)]
    draft = _Memory(
        game=shorten(f"{game}: {brief}" if game and brief else game or brief, limits.game_chars),
        session=shorten(clean(inputs.session_note or ""), limits.session_chars),
        last_time=shorten(clean(inputs.last_session or ""), limits.last_session_chars),
        player=take_within(facts, limits.player_chars),
        unsure=take_within(unsure, limits.unsure_chars),
    )
    return draft.fit(limits.memory_chars)


def _live(inputs: ContextInputs, limits: ContextLimits) -> str:
    live = [(clean(key), clean(value)) for key, value in inputs.live_state.items()]
    started, now = inputs.session_started, inputs.now
    asked = inputs.asked
    recalled = [
        shorten(clean(item), limits.recalled_item_chars)
        for item in inputs.recalled[: limits.max_recalled]
        if clean(item)
    ]
    draft = _Live(
        time=f"{session_clock(now - started)} into the session" if started and now else "",
        now=shorten("; ".join(f"{key}: {value}" for key, value in live), limits.now_chars),
        asked=format_asked(asked, limits.asked_chars) if asked and clean(asked.text) else "",
        recalled=take_within(recalled, limits.recall_chars),
    )
    return draft.fit(limits.live_chars)


def build_context(inputs: ContextInputs, limits: ContextLimits = DEFAULT_LIMITS) -> TalkerContext:
    history, left_out = history_turns(
        inputs.turns, limits.history_chars, limits.turn_chars, inputs.session_started
    )
    if left_out:
        # Expected in a long session: older turns are left to the session note.
        log.info("Conversation over its budget; left out the oldest %d items", left_out)
    return TalkerContext(_memory(inputs, limits), history, _live(inputs, limits))


def render_context(inputs: ContextInputs, limits: ContextLimits = DEFAULT_LIMITS) -> str:
    """The three layers as one string, as the Control Center shows them."""
    return build_context(inputs, limits).render()
