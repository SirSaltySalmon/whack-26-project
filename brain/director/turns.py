"""The model turns the director runs in its speech slot: answering the player, and giving a tip.

Kept out of director.py so the director stays about when to speak and what holds its one slot.

A tip is the one turn the player didn't start that may use a tool, an intended exception to tools
running only on player turns. It gets point_at and nothing else, at most once, so a tip costs at
most one vision call and can never open a page or a card. The rules still decide when a tip comes,
and hints off skips it before any model is called.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from brain.agent.tools import ToolRegistry, TurnContext
from brain.agent.turn import run_turn
from brain.director.talker import ADVICE_PROMPT, is_skip, reply, wants_detail
from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, TextLLM, ToolLLM
from brain.memory.layers import TalkerContext

log = logging.getLogger(__name__)

# Showing where to go next is what makes a tip easy to act on mid-game; nothing else is needed.
TIP_TOOLS = ("point_at",)
# What a tip's context is fetched for, so memory recalls progress and goals.
TIP_QUERY = "progress goal next"


@dataclass(frozen=True)
class Persona:
    """Who's talking. Read fresh for every turn, because the player can change it mid-session."""

    name: str
    tone: str
    max_words: int
    hints: bool

    @classmethod
    def of(cls, name: str, tone: str, instructions: str, max_words: int, hints: bool) -> "Persona":
        """The personality's tone, with the player's own instructions added when they wrote any."""
        instructions = instructions.strip()
        if instructions:
            tone += f"\nPlayer custom instructions (keep truth and trust rules): {instructions}"
        return cls(name, tone, max_words, hints)


async def talker_reply(
    talker: TextLLM, prompt: str, persona: Persona, context: TalkerContext, detail: bool = False
) -> str | None:
    """A reply with no tools, for reactions, and for tips and turns when there's no agent.
    Only a player's turn can ask for detail, so callers pass it rather than it being read here."""
    text = await reply(
        talker,
        prompt,
        persona.name,
        persona.max_words,
        context,
        persona.tone,
        hints=persona.hints,
        detail=detail,
    )
    return None if not text or is_skip(text) else text


async def _no_filler() -> None:
    """Nobody is waiting on a tip, so a "one sec" line would only interrupt the game."""


def tip_tools(tools: ToolRegistry | None) -> ToolRegistry | None:
    """One tip's tools, or None when it can't point and should go to the plain talker."""
    if tools is None:
        return None
    pointing = tools.only(*TIP_TOOLS)
    # once() per tip, so its count starts again for the next one.
    return pointing.once() if pointing.names else None


async def tip_reply(
    agent: ToolLLM, tools: ToolRegistry, persona: Persona, context: TalkerContext
) -> str | None:
    """Returns the tip to say, or None to stay quiet. Nobody asked, so failing is just silence."""
    try:
        text = await run_turn(
            agent,
            tools,
            ADVICE_PROMPT,
            persona.name,
            persona.tone,
            persona.max_words,
            context,
            TurnContext(),
            _no_filler,
            # A pointer with no words is fine for a tip, but "there you go" about nothing isn't.
            "",
            hints=persona.hints,
            # One round, so the model can't follow its point_at with another tool call.
            max_rounds=1,
        )
    except (LLMUnavailableError, LLMEmptyResponseError) as exc:
        log.warning("No tip this time: %s", exc)
        return None
    return None if not text or is_skip(text) else text


async def give_tip(
    agent: ToolLLM | None,
    talker: TextLLM | None,
    tools: ToolRegistry | None,
    persona: Persona,
    context: TalkerContext,
) -> str | None:
    """A tip from the agent when it can point, else from the plain talker, else none."""
    pointing = tip_tools(tools)
    if agent is not None and pointing is not None:
        return await tip_reply(agent, pointing, persona, context)
    if talker is None:
        log.warning("No talker LLM configured; no tip")
        return None
    # Replays have no agent, and a tip that can't point is still worth saying.
    return await talker_reply(talker, ADVICE_PROMPT, persona, context)


async def player_reply(
    agent: ToolLLM,
    tools: ToolRegistry,
    transcript: str,
    turn: TurnContext,
    persona: Persona,
    context: TalkerContext,
    looking: Callable[[], Awaitable[None]],
    done_line: str,
    unavailable: Callable[[], str],
    started: float,
) -> str | None:
    """Always has an answer when the model fails, because the player is waiting on one."""
    try:
        text = await run_turn(
            agent,
            tools,
            transcript,
            persona.name,
            persona.tone,
            persona.max_words,
            context,
            turn,
            looking,
            done_line,
            hints=persona.hints,
            detail=wants_detail(transcript),
        )
    except (LLMUnavailableError, LLMEmptyResponseError) as exc:
        log.warning("Player turn unavailable: %s", exc)
        text = unavailable()
    except Exception:
        # A vendor error of any kind still gets an answer rather than silence.
        log.exception("Player turn failed")
        text = unavailable()
    log.info("Latency: player turn took %.0f ms", (time.monotonic() - started) * 1000)
    if not text:
        log.warning("Player turn produced no reply for: %s", transcript)
    return text
