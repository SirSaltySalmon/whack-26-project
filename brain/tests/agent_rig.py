"""Builds AgentTools with every vendor faked, shared by the tests of each tool."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from brain.agent.handlers import AgentLimits, AgentTools
from brain.agent.tools import TurnContext
from brain.capture.ring_buffer import Frame, RingBuffer
from brain.llm.base import TextLLM, ToolCall, VisionLLM
from brain.research import WikiCard
from brain.tests.fakes import (
    FakeMemory,
    FakeOverlay,
    FakeTextLLM,
    FakeVision,
    VisionReply,
    make_buffer,
)

# Fits both reply shapes, because extra fields are ignored when a reply is validated.
SEEN = {"answer": "A red door.", "sure": True, "found": False, "label": "", "box_px": []}
LOOK = {"question": "what's that?", "area": "whole"}
POINT = {"target": "the door"}
BOTH_VISION_TOOLS = [("look_closer", LOOK), ("point_at", POINT)]


class FakeResearch:
    def __init__(self, card: WikiCard | None) -> None:
        self.card = card
        self.queries: list[str] = []
        self.questions: list[str] = []

    async def lookup(self, query: str, question: str = "") -> WikiCard | None:
        self.queries.append(query)
        self.questions.append(question)
        return self.card


@dataclass
class Rig:
    tools: AgentTools
    buffer: RingBuffer
    overlay: FakeOverlay
    vision: FakeVision
    deep: FakeTextLLM
    memory: FakeMemory
    context_questions: list[str]

    async def run(self, tool: str, turn: TurnContext | None = None, **arguments: Any) -> str:
        """Goes through the registry, the way a model's call does."""
        return await self.tools.registry().run(ToolCall(tool, arguments), turn or TurnContext())


def rig(
    *frames: Frame,
    reply: VisionReply = SEEN,
    scale: float = 1.0,
    padding: int = 0,
    max_edge: int = 320,
    max_age: float = 15.0,
    deep: FakeTextLLM | None = None,
    memory: FakeMemory | None = None,
    context: str = "",
    research: FakeResearch | None = None,
    get_vision: Callable[[], VisionLLM] | None = None,
    get_deep: Callable[[], TextLLM] | None = None,
    debug: bool = False,
) -> Rig:
    """`get_vision` and `get_deep` replace the fakes' getters, since a missing key raises there."""
    buffer = make_buffer(*frames, capacity=8)
    overlay = FakeOverlay(display_scale=scale)
    vision = FakeVision(reply)
    deep_llm = deep or FakeTextLLM(["Plan it out."])
    memory = memory or FakeMemory()
    context_questions: list[str] = []

    async def gather_context(question: str) -> str:
        context_questions.append(question)
        return context

    tools = AgentTools(
        buffer,
        overlay,
        get_vision or (lambda: vision),
        get_deep or (lambda: deep_llm),
        memory,
        gather_context,
        AgentLimits(padding, max_edge, max_age, pointer_ttl_ms=4000, show_sightings=debug),
    )
    tools.research = research  # type: ignore[assignment]
    return Rig(tools, buffer, overlay, vision, deep_llm, memory, context_questions)
