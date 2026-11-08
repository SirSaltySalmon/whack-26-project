"""Every prompt starts with the rules, then MEMORY, both cached because they rarely change. What
changes every call, LIVE, opens the latest message instead, after the cached conversation."""

from brain.agent.tools import ToolRegistry, TurnContext
from brain.agent.turn import run_turn
from brain.director.talker import build_system
from brain.llm.base import SystemPart, ToolStep
from brain.memory.context import CONTEXT_PREAMBLE
from brain.memory.layers import TalkerContext
from brain.tests.agent_rig import rig
from brain.tests.fakes import ScriptedToolLLM

MEMORY = "GAME: Terraria"
LIVE = "NOW: danger: high"
CONTEXT = TalkerContext(memory=MEMORY, live=LIVE)


def test_the_rules_and_memory_are_both_cached() -> None:
    stable, memory = build_system("supportive", "Warm.", 100, MEMORY)
    assert stable.cache and memory == SystemPart(MEMORY, cache=True)
    assert "supportive" in stable.text and stable.text.endswith(CONTEXT_PREAMBLE)
    assert MEMORY not in stable.text


def test_the_cached_rules_are_the_same_whatever_memory_holds() -> None:
    # Any change in them would miss the cache on every call.
    first = build_system("supportive", "Warm.", 100, "GAME: Minecraft")
    second = build_system("supportive", "Warm.", 100, MEMORY)
    assert first[0] == second[0]
    assert build_system("supportive", "Warm.", 100, "") == (first[0],)


async def no_filler() -> None:
    pass


async def test_a_player_turn_caches_the_tool_guidance_and_memory_but_not_live() -> None:
    llm = ScriptedToolLLM([ToolStep("Sure.")])
    registry, turn = ToolRegistry([]), TurnContext()
    await run_turn(llm, registry, "hi", "supportive", "Warm.", 100, CONTEXT, turn, no_filler, "")
    stable, memory = llm.system_parts
    assert isinstance(stable, SystemPart) and stable.cache
    assert "look_closer" in stable.text and stable.text.endswith(CONTEXT_PREAMBLE)
    assert memory == SystemPart(CONTEXT.memory_block(), cache=True)
    assert LIVE not in llm.system and LIVE in llm.sends[0]


async def test_think_hard_caches_its_instructions_and_memory_but_not_live() -> None:
    r = rig(context=CONTEXT)
    await r.run("think_hard", question="How should I plan this?")
    stable, memory = r.deep.system_parts
    assert isinstance(stable, SystemPart) and stable.cache
    assert CONTEXT_PREAMBLE in stable.text and MEMORY not in stable.text
    assert memory == SystemPart(CONTEXT.memory_block(), cache=True)
    assert LIVE not in r.deep.system and LIVE in r.deep.prompts[0]
