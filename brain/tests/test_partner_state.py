"""The partner's own state, shown to it as YOU: its last question and the tips it gave.

It's what stops it asking the same question twice or repeating a tip, so these check it's built
only from lines really said, and that it reaches every kind of reply.
"""

from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.director.actions import AskTalker, GiveAdvice, ReactToEvent
from brain.director.partner_state import MAX_CHARS, MAX_TIPS, QUESTION_MAX_AGE_S, PartnerState
from brain.director.talker import ADVICE_PROMPT, drop_narration
from brain.llm.base import ToolStep
from brain.memory.layers import TalkerContext
from brain.tests.director_rig import Rig
from brain.tests.fakes import FakeTextLLM, FakeVoice, ScriptedToolLLM

QUESTION = "Want to build a house first?"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_spoken_question_waits_until_a_player_turn_ends() -> None:
    clock = Clock()
    state = PartnerState(clock)
    state.spoke(QUESTION)
    clock.now += 40
    assert state.render() == f'your last question (40 s ago, not answered before now): "{QUESTION}"'
    with state.replying():
        # While their words are being answered, they may be the answer: still "before now".
        assert "not answered before now" in state.render()
    assert "they've replied since" in state.render()


def test_a_question_asked_in_the_reply_itself_is_still_waiting() -> None:
    state = PartnerState(Clock())
    state.spoke("Ready?")
    with state.replying():
        state.spoke(QUESTION)
    assert QUESTION in state.render() and "not answered before now" in state.render()


def test_lines_that_ask_nothing_leave_the_last_question_alone() -> None:
    state = PartnerState(Clock())
    assert state.render() == ""
    state.spoke("Nice swing.")
    assert state.render() == ""
    state.spoke(QUESTION)
    state.spoke("Watch out.")
    assert QUESTION in state.render()


def test_an_old_question_is_left_out() -> None:
    clock = Clock()
    state = PartnerState(clock)
    state.spoke(QUESTION)
    clock.now += QUESTION_MAX_AGE_S + 1
    assert state.render() == ""


def test_tips_keep_the_last_five_newest_first_with_their_ages() -> None:
    clock = Clock()
    state = PartnerState(clock)
    for number in range(MAX_TIPS + 2):
        state.tipped(f"Tip {number}.")
        clock.now += 60
    text = state.render()
    assert text.startswith(
        'tips you gave, newest first: "Tip 6." (1 min ago); "Tip 5." (2 min ago)'
    )
    assert "Tip 2." in text and "Tip 1." not in text and "Tip 0." not in text


def test_it_stays_within_its_cap_by_dropping_the_oldest_tips() -> None:
    state = PartnerState(Clock())
    state.spoke("Do you " + "really " * 60 + "want that?")
    for number in range(MAX_TIPS):
        state.tipped(f"Tip {number} " + "and more " * 30)
    text = state.render()
    assert len(text) <= MAX_CHARS
    assert "Tip 4" in text and "Tip 0" not in text
    assert text.startswith("your last question")


def test_the_leak_filter_drops_a_line_naming_you_but_keeps_emphasis() -> None:
    assert drop_narration("Craft a bed. As listed under YOU, I said that.") == "Craft a bed."
    assert drop_narration("I believe in YOU. Go!") == "I believe in YOU. Go!"


def test_the_tip_prompt_points_at_you() -> None:
    assert "listed under YOU" in ADVICE_PROMPT and "different kind of tip" in ADVICE_PROMPT


class WikiInput(BaseModel):
    query: str


async def _never(_arguments: WikiInput, _turn: TurnContext) -> str:
    raise AssertionError("No test calls a tool")


# With a tool registered, player turns go through the agent, as they do live.
TOOLS = [Tool("lookup_wiki", "Looks up.", WikiInput, _never)]


def rig_with(voice: FakeVoice | None = None, *replies: str) -> tuple[Rig, ScriptedToolLLM]:
    agent = ScriptedToolLLM([ToolStep(text) for text in replies])
    return Rig(voice=voice, agent=agent, talker=FakeTextLLM(["Yikes."]), tools=TOOLS), agent


async def test_you_reaches_player_turns_reactions_and_tips() -> None:
    rig, agent = rig_with(None, QUESTION, "Nice, a big one.")
    talker = rig.director._talker
    assert isinstance(talker, FakeTextLLM)
    await rig.director._perform(AskTalker("hi"))
    assert "YOU:" not in agent.sends[0]

    await rig.director._perform(ReactToEvent("danger_started", {"threats": ["Slime"]}))
    assert f'not answered before now): "{QUESTION}"' in talker.prompts[0]

    await rig.director._perform(AskTalker("yes, a big one"))
    assert f'not answered before now): "{QUESTION}"' in agent.sends[1]

    # A tip without an agent that can point goes to the plain talker.
    rig.director._tools = None
    await rig.director._perform(GiveAdvice())
    assert "they've replied since" in talker.prompts[1] and talker.prompts[1].endswith(
        ADVICE_PROMPT
    )


async def test_a_spoken_tip_is_listed_for_the_next_one() -> None:
    rig, _agent = rig_with()
    rig.director._tools = None
    talker = rig.director._talker
    assert isinstance(talker, FakeTextLLM)
    talker.chunks = ["Mine the copper by the cave."]
    await rig.director._perform(GiveAdvice())
    await rig.director._perform(GiveAdvice())
    assert "YOU:" not in talker.prompts[0]
    assert 'tips you gave, newest first: "Mine the copper by the cave."' in talker.prompts[1]


async def test_a_question_that_was_never_said_is_not_listed() -> None:
    # The voice refuses every line, as when the player is talking over it.
    rig, agent = rig_with(FakeVoice(accepts=False), QUESTION, "Okay.")
    await rig.director._perform(AskTalker("hi"))
    await rig.director._perform(AskTalker("hello?"))
    assert all("YOU:" not in sent for sent in agent.sends)


async def test_you_is_added_even_when_memory_fails() -> None:
    async def broken(_query: str, _current: str | None) -> TalkerContext:
        raise RuntimeError("database locked")

    agent = ScriptedToolLLM([ToolStep(QUESTION), ToolStep("Okay.")])
    rig = Rig(agent=agent, tools=TOOLS, context=broken)
    await rig.director._perform(AskTalker("hi"))
    await rig.director._perform(AskTalker("what?"))
    assert QUESTION in agent.sends[1]
