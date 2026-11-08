"""A turn cut off before its reply was said carries its words into the player's next turn.

From a live session: Flux split "I like building a lot, but I'm not doing that. Today." in two,
the second part cancelled the first one's reply, and alone "today." made the partner ask its
question again.
"""

import asyncio

from brain.director.carry import CARRY_S, Carry
from brain.director.rules import AskTalker
from brain.events import GameEvent, PlayerSpeech, PlayerStartedSpeaking
from brain.llm.base import ToolStep
from brain.tests.director_rig import Rig, Stuck, settle
from brain.tests.fakes import FakeTextLLM, ScriptedToolLLM

FIRST = "I like building a lot, but I'm not doing that."
SECOND = "today."


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_words_cut_off_before_a_reply_start_the_next_turn() -> None:
    carry = Carry(Clock())
    with carry.answering(AskTalker(FIRST)):
        carry.cut_off()
    assert carry.into(AskTalker(SECOND, started_at=7.0)) == AskTalker(f"{FIRST} {SECOND}", 7.0)
    # Carried once only.
    assert carry.into(AskTalker("later")).transcript == "later"


def test_nothing_carries_once_something_was_said_for_the_turn() -> None:
    carry = Carry(Clock())
    with carry.answering(AskTalker(FIRST)):
        carry.spoke()
        carry.cut_off()  # A barge-in on the reply itself: they heard it start.
    assert carry.into(AskTalker(SECOND)).transcript == SECOND


def test_a_finished_turn_carries_nothing_into_a_later_cancel() -> None:
    carry = Carry(Clock())
    with carry.answering(AskTalker(FIRST)):
        pass  # Finished with nothing to say.
    carry.cut_off()  # Cancelling something else, such as a reaction.
    assert carry.into(AskTalker(SECOND)).transcript == SECOND


def test_an_older_turn_finishing_late_leaves_the_newer_one_open() -> None:
    carry = Carry(Clock())
    older = carry.answering(AskTalker("older"))
    older.__enter__()
    with carry.answering(AskTalker(FIRST)):
        older.__exit__(None, None, None)
        carry.cut_off()
    assert carry.into(AskTalker(SECOND)).transcript == f"{FIRST} {SECOND}"


def test_old_cut_off_words_are_not_carried() -> None:
    clock = Clock()
    carry = Carry(clock)
    with carry.answering(AskTalker(FIRST)):
        carry.cut_off()
    clock.now += CARRY_S + 1
    assert carry.into(AskTalker(SECOND)).transcript == SECOND


async def test_a_split_answer_reaches_the_model_whole() -> None:
    stuck = Stuck("Stale reply.")
    agent = ScriptedToolLLM([stuck, ToolStep("Building it is.")])
    rig = Rig(agent=agent)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript=FIRST, ts=10.0))
        await rig.publish(PlayerStartedSpeaking(ts=11.0))
        assert stuck.cancelled
        await rig.publish(PlayerSpeech(transcript=SECOND, ts=12.0))
    assert agent.sends == [FIRST, f"{FIRST} {SECOND}"]
    assert rig.voice.said == ["Building it is."]


async def test_a_turn_that_was_answered_is_not_repeated() -> None:
    agent = ScriptedToolLLM([ToolStep("Nice."), ToolStep("Sure.")])
    rig = Rig(agent=agent)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript=FIRST, ts=10.0))
        await rig.publish(PlayerStartedSpeaking(ts=11.0))
        await rig.publish(PlayerSpeech(transcript=SECOND, ts=12.0))
    assert agent.sends == [FIRST, SECOND]


async def test_a_cancelled_reaction_carries_nothing() -> None:
    gate = asyncio.Event()
    talker = FakeTextLLM(["Stale reaction."], gate=gate)
    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(talker=talker, agent=agent)
    async with rig.running():
        await rig.publish(GameEvent("danger_started", ts=10.0))
        assert len(talker.prompts) == 1  # The reaction holds the slot.
        await rig.publish(PlayerStartedSpeaking(ts=11.0))
        await rig.publish(PlayerSpeech(transcript=SECOND, ts=12.0))
        gate.set()
        await settle()
    assert agent.sends == [SECOND]
    assert rig.voice.said == ["Reply."]
