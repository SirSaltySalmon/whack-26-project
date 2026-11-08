"""Runs player questions through the real turn code and prints the tools it called and its reply.

Uses the configured talker (paid: one to three short calls per question) and the game's real wiki.
There's no game running, so the screen tools get no frames and memory is a stub: this checks tool
choice and wiki answers, not vision. Without arguments it runs the built-in cases.

Usage: python scripts/check_turns.py [--game Terraria] ["question" ...]
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.agent.handlers import AgentLimits, AgentTools  # noqa: E402
from brain.agent.tools import ToolCall, TurnContext  # noqa: E402
from brain.agent.turn import run_turn  # noqa: E402
from brain.capture.ring_buffer import RingBuffer  # noqa: E402
from brain.config import Settings  # noqa: E402
from brain.director.personalities import load_personalities  # noqa: E402
from brain.llm.factory import LLMFactory  # noqa: E402
from brain.research import WikiResearch  # noqa: E402
from brain.tests.fakes import FakeMemory, FakeOverlay  # noqa: E402

# Each case names the tools a good turn would call. Any of them counts, and an empty set means
# no tool at all. Screen questions expect look_closer even though it can't see here.
CASES: list[tuple[str, set[str]]] = [
    ("How do I cheat myself more max health in journey mode?", {"lookup_wiki"}),
    ("How do I summon the Eye of Cthulhu?", {"lookup_wiki"}),
    ("What does a life fruit do?", {"lookup_wiki"}),
    ("How do I craft a wooden bow?", {"lookup_wiki"}),
    ("Where do I find life crystals?", {"lookup_wiki"}),
    ("What drops a shackle?", {"lookup_wiki"}),
    ("Open the wiki page for the Guide.", {"lookup_wiki"}),
    ("What am I holding right now?", {"look_closer"}),
    ("Hey, how's it going?", set()),
]
CONTEXT = "GAME: {game}\nNOW: gameplay, on the surface in a forest, daytime. Health looks full."


async def ask(settings: Settings, research: WikiResearch | None, question: str) -> dict[str, Any]:
    tools = AgentTools(
        RingBuffer(capacity=4),
        FakeOverlay(display_scale=1.0),
        LLMFactory(settings).closeup,
        LLMFactory(settings).deep,
        FakeMemory(),
        _no_context,
        AgentLimits(settings.mask_padding_px, settings.ai_image_max_edge_px, 15.0, 4000),
    )
    tools.research = research
    registry = tools.registry()
    calls: list[str] = []
    run = registry.run

    async def recorded(call: ToolCall, turn: TurnContext) -> str:
        output = await run(call, turn)
        calls.append(f"{call.name}({call.args}) -> {output[:300]!r}")
        return output

    registry.run = recorded  # type: ignore[method-assign]
    book = load_personalities()
    started = time.monotonic()
    reply = await run_turn(
        LLMFactory(settings).talker(),
        registry,
        question,
        book.default,
        book.tone(book.default),
        settings.talker_max_words,
        CONTEXT.format(game=settings.game_title or "the game"),
        TurnContext(),
        _nothing,
        "There you go.",
    )
    return {"calls": calls, "reply": reply, "ms": (time.monotonic() - started) * 1000}


async def _no_context(_question: str) -> str:
    return ""


async def _nothing() -> None:
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="*")
    parser.add_argument("--game", default="Terraria")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings(game_title=args.game)
    research = await WikiResearch.for_game(args.game)
    if research is None:
        print(f"No wiki found for {args.game}; wiki questions will say so")
    cases = [(q, set()) for q in args.questions] if args.questions else CASES
    passed = 0
    for question, expected in cases:
        result = await ask(settings, research, question)
        used = {call.split("(", 1)[0] for call in result["calls"]}
        ok = bool(used & expected) if expected else not used
        passed += ok
        mark = "" if args.questions else (" ok" if ok else f" EXPECTED {sorted(expected)}")
        print(f"\n### {question}  ({result['ms']:.0f} ms){mark}")
        for call in result["calls"]:
            print(f"  tool: {call}")
        print(f"  says: {result['reply']}")
    if not args.questions:
        print(f"\nTool choice: {passed} of {len(cases)} as expected")
    if research is not None:
        await research.aclose()


if __name__ == "__main__":
    asyncio.run(main())
