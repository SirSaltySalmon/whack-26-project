"""A turn that's checking the screen must still answer when the player talks over it."""

import asyncio

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.director import director as director_module
from brain.events import PlayerSpeech, PlayerStartedSpeaking
from brain.llm.base import ToolCall, ToolStep
from brain.tests.director_rig import LOOKING, Rig, settle, until
from brain.tests.fakes import ScriptedToolLLM

ANSWER = "It's the Guide."


class NoInput(BaseModel):
    pass


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(director_module, "SPEAK_RETRY_S", 0.001)


def checking_rig(*replies: str) -> tuple[Rig, ScriptedToolLLM, asyncio.Event]:
    """A rig whose first turn calls a screen check that waits for the returned gate."""
    gate = asyncio.Event()

    async def check(_arguments: NoInput, _turn: TurnContext) -> str:
        await gate.wait()
        return "a man in brown"

    agent = ScriptedToolLLM(
        [ToolStep("", (ToolCall("check", {}),)), *(ToolStep(reply) for reply in replies)]
    )
    rig = Rig(agent=agent, tools=[Tool("check", "Checks the screen.", NoInput, check)])
    return rig, agent, gate


async def test_talking_during_a_check_does_not_cancel_it() -> None:
    rig, _agent, gate = checking_rig(ANSWER)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="what's next to me?"))
        assert rig.voice.said == [LOOKING] and rig.director.checking

        # PipecatVoice refuses to speak over the player, so the answer has to wait for silence.
        rig.voice.accepts = False
        await rig.publish(PlayerStartedSpeaking())
        gate.set()
        await until(lambda: ANSWER in rig.voice.said)
        assert rig.spoken == []

        rig.voice.accepts = True
        await until(lambda: rig.spoken == [ANSWER])
        await settle()
    assert not rig.director.checking


async def test_a_new_question_waits_for_the_check_to_answer() -> None:
    rig, agent, gate = checking_rig(ANSWER, "Anything else?")
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="what's next to me?"))
        await rig.publish(PlayerSpeech(transcript="so, answer?"))
        assert rig.director.checking
        assert agent.sends == ["what's next to me?"]  # The second waits its turn.

        gate.set()
        await until(lambda: len(rig.spoken) == 2)
    assert agent.sends == ["what's next to me?", "so, answer?"]
    assert rig.spoken == [ANSWER, "Anything else?"]


async def test_an_answer_is_dropped_if_the_player_never_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 0.05)
    rig, _agent, gate = checking_rig(ANSWER)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="what's that?"))
        rig.voice.accepts = False
        gate.set()
        await until(lambda: not rig.director.checking)

        # Once dropped, it isn't said late when the player finally stops.
        rig.voice.accepts = True
        await settle()
    assert ANSWER in rig.voice.said  # It was tried,
    assert rig.spoken == []  # but never accepted.
