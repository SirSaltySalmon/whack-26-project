"""How much a player turn says: brief unless they ask for detail, and never its pre-tool words."""

from brain.llm.base import ToolStep
from brain.tests.fakes import ScriptedToolLLM
from brain.tests.test_agent_turn import Harness, asks

# Four sentences of 13 words each.
LONG = "This is one sentence that runs to twelve words or so in all. " * 4


async def test_a_reply_nobody_asked_detail_for_is_cut_to_whole_brief_sentences() -> None:
    llm = ScriptedToolLLM([ToolStep(LONG)])
    text = await Harness().run(llm, max_words=100)
    assert text == " ".join(LONG.split()[:26])  # Two whole sentences fit in 30 words.


async def test_asking_for_detail_lifts_the_cap_and_says_so_in_the_prompt() -> None:
    llm = ScriptedToolLLM([ToolStep(LONG)])
    text = await Harness().run(llm, max_words=100, detail=True)
    assert text == " ".join(LONG.split())
    assert "up to 100 words" in llm.system


async def test_words_written_before_a_tool_call_are_never_said() -> None:
    before = ToolStep("Let me check that for you.", asks("a").calls)
    llm = ScriptedToolLLM([before, ToolStep("It's a slime.")])
    assert await Harness().run(llm) == "It's a slime."
