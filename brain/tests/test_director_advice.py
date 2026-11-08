"""What the director does with a tip: run it through the agent with only point_at, at most once,
with no filler, or through the plain talker when there's no agent. test_advice.py has the rules."""

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.director.talker import ADVICE_PROMPT
from brain.director.turns import TIP_QUERY
from brain.events import OverlayConnected, Tick
from brain.llm.base import LLMUnavailableError, ToolCall, ToolStep
from brain.tests.director_rig import LOOKING, Rig
from brain.tests.fakes import FakeTextLLM, ScriptedToolLLM

FIRST_S = 90.0
GREETING = "Brain connected."
TIP = "Craft a workbench, it's right there."


class PointInput(BaseModel):
    target: str


class Tools:
    """A point_at and a lookup_wiki that record their calls, so a test sees which ran."""

    def __init__(self) -> None:
        self.pointed: list[str] = []
        self.looked_up = 0

    async def point(self, arguments: PointInput, _turn: TurnContext) -> str:
        self.pointed.append(arguments.target)
        return "The pointer is now beside it."

    async def wiki(self, _arguments: PointInput, _turn: TurnContext) -> str:
        self.looked_up += 1
        return "A page."

    def all(self) -> list[Tool]:
        return [
            Tool("point_at", "Points.", PointInput, self.point),
            Tool("lookup_wiki", "Looks up.", PointInput, self.wiki),
        ]


def points_at(*targets: str) -> ToolStep:
    return ToolStep("", tuple(ToolCall("point_at", {"target": t}) for t in targets))


async def due_tip(rig: Rig) -> None:
    await rig.publish(OverlayConnected(display_scale=1.0, ts=0.0))
    await rig.publish(Tick(ts=FIRST_S))


def tip_rig(**kwargs: object) -> Rig:
    # No questions, so the tick that's due brings up only the tip.
    return Rig(advice_gap_s=180.0, advice_first_s=FIRST_S, quiet_s=1e9, **kwargs)  # type: ignore[arg-type]


async def test_a_tip_can_point_at_what_it_suggests_and_offers_no_other_tool() -> None:
    tools = Tools()
    agent = ScriptedToolLLM([points_at("workbench"), ToolStep(TIP)])
    rig = tip_rig(agent=agent, tools=tools.all())
    async with rig.running():
        await due_tip(rig)
    assert [d.name for d in agent.tools] == ["point_at"]
    assert agent.sends == [ADVICE_PROMPT]
    assert tools.pointed == ["workbench"]
    # Nobody asked, so no "one sec", and nothing to survive a barge-in for.
    assert LOOKING not in rig.voice.said and not rig.director.checking
    assert rig.voice.said == [GREETING, TIP]
    assert rig.spoken == [TIP]


async def test_a_tip_points_at_most_once_and_then_must_speak() -> None:
    tools = Tools()
    agent = ScriptedToolLLM([points_at("workbench", "furnace"), ToolStep(TIP)])
    rig = tip_rig(agent=agent, tools=tools.all())
    async with rig.running():
        await due_tip(rig)
    assert tools.pointed == ["workbench"]  # One vision call at most.
    assert agent.results[0].allow_tools is False
    assert agent.model_calls == 2
    assert rig.voice.said == [GREETING, TIP]


async def test_a_tip_that_needs_no_pointer_takes_one_model_call() -> None:
    agent = ScriptedToolLLM([ToolStep(TIP)])
    rig = tip_rig(agent=agent, tools=Tools().all())
    async with rig.running():
        await due_tip(rig)
    assert agent.model_calls == 1
    assert rig.voice.said == [GREETING, TIP]


async def test_a_tip_gets_context_for_progress_and_goals() -> None:
    queries: list[str] = []

    async def context(query: str) -> str:
        queries.append(query)
        return "PLAYER: playthrough / progress: early game (observed)"

    agent = ScriptedToolLLM([ToolStep(TIP)])
    rig = tip_rig(agent=agent, tools=Tools().all(), context=context)
    async with rig.running():
        await due_tip(rig)
    assert queries == [TIP_QUERY]
    assert "playthrough / progress: early game" in agent.system


@pytest.mark.parametrize("words", ["SKIP", "Skip.", " skip! "])
async def test_a_tip_that_skips_stays_quiet_even_after_pointing(words: str) -> None:
    agent = ScriptedToolLLM([points_at("workbench"), ToolStep(words)])
    rig = tip_rig(agent=agent, tools=Tools().all())
    async with rig.running():
        await due_tip(rig)
    assert rig.voice.said == [GREETING]


async def test_a_tip_whose_model_is_unavailable_stays_quiet() -> None:
    # A player turn would say it can't help, but nobody asked for a tip.
    rig = tip_rig(agent=ScriptedToolLLM([LLMUnavailableError("over quota")]), tools=Tools().all())
    async with rig.running():
        await due_tip(rig)
    assert rig.voice.said == [GREETING]


async def test_without_an_agent_a_tip_comes_from_the_plain_talker() -> None:
    talker = FakeTextLLM([TIP])
    rig = tip_rig(talker=talker)
    async with rig.running():
        await due_tip(rig)
    assert talker.prompts == [ADVICE_PROMPT]
    assert rig.voice.said == [GREETING, TIP]


async def test_with_no_pointer_to_offer_a_tip_comes_from_the_plain_talker() -> None:
    talker = FakeTextLLM([TIP])
    agent = ScriptedToolLLM([])
    rig = tip_rig(talker=talker, agent=agent)
    async with rig.running():
        await due_tip(rig)
    assert agent.model_calls == 0
    assert rig.voice.said == [GREETING, TIP]


async def test_the_plain_talker_saying_skip_stays_quiet() -> None:
    rig = tip_rig(talker=FakeTextLLM(["SKIP."]))
    async with rig.running():
        await due_tip(rig)
    assert rig.voice.said == [GREETING]


async def test_hints_off_means_no_tips_and_no_model_call() -> None:
    talker = FakeTextLLM([TIP])
    agent = ScriptedToolLLM([ToolStep(TIP)])
    rig = tip_rig(talker=talker, agent=agent, tools=Tools().all(), proactive=False)
    async with rig.running():
        await due_tip(rig)
    assert talker.prompts == [] and agent.model_calls == 0
    assert rig.voice.said == [GREETING]


async def test_a_spoken_tip_restarts_the_quiet_stretch() -> None:
    # Two tips can't land back to back, even with a tiny gap, because the first was just said.
    talker = FakeTextLLM([TIP])
    rig = Rig(talker=talker, advice_gap_s=1.0, advice_first_s=FIRST_S, quiet_s=1e9)
    async with rig.running():
        await due_tip(rig)
        await rig.publish(Tick(ts=FIRST_S + 5.0))
        await rig.publish(Tick(ts=FIRST_S + 20.0))
    assert rig.voice.said == [GREETING, TIP, TIP]
    assert talker.prompts == [ADVICE_PROMPT, ADVICE_PROMPT]


async def test_a_tip_comes_from_the_thinking_model_when_there_is_one() -> None:
    agent = ScriptedToolLLM([])
    tip_llm = ScriptedToolLLM([ToolStep(TIP)])
    rig = tip_rig(agent=agent, tip_llm=tip_llm, tools=Tools().all())
    async with rig.running():
        await due_tip(rig)
    assert agent.model_calls == 0 and tip_llm.model_calls == 1
    assert rig.voice.said == [GREETING, TIP]


async def test_a_tip_that_cant_point_comes_from_the_thinking_model_too() -> None:
    talker = FakeTextLLM(["Not this one."])
    tip_llm = FakeTextLLM([TIP])
    rig = tip_rig(talker=talker, tip_llm=tip_llm)
    async with rig.running():
        await due_tip(rig)
    assert talker.prompts == [] and tip_llm.prompts == [ADVICE_PROMPT]
    assert rig.voice.said == [GREETING, TIP]
