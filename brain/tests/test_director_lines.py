"""What the director says besides plain replies: questions, barks, and how settings shape it."""

import asyncio

import pytest

from brain.director.talker import HINTS_OFF, HINTS_ON
from brain.events import GameEvent, OverlayConnected, PlayerSpeech, PlayerStartedSpeaking
from brain.llm.base import ToolStep
from brain.tests.director_rig import TONE, Rig, Stuck, settle
from brain.tests.fakes import FakeMemory, FakeTextLLM, FakeVoice, ScriptedToolLLM
from shared.protocol.messages import QuestionAsk

QUESTION = QuestionAsk(question_id="q1", text="Where's your base?", options=["East", "West"])
BARKS = {"danger_started": "danger"}


async def test_a_question_is_shown_and_spoken() -> None:
    memory = FakeMemory([QUESTION])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
    assert rig.overlay.sent == [QUESTION]
    assert rig.voice.said == ["Brain connected.", QUESTION.text]
    assert rig.spoken == [QUESTION.text]
    assert memory.questions_taken == 1


async def test_no_open_question_stays_quiet() -> None:
    memory = FakeMemory([])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
    assert memory.questions_taken == 1  # It did ask memory, and memory had nothing.
    assert rig.overlay.sent == []
    assert rig.voice.said == ["Brain connected."]
    assert rig.spoken == []


async def test_a_question_is_still_shown_when_the_voice_drops_it() -> None:
    # take_question has already marked it asked, so hiding it would lose it.
    rig = Rig(voice=FakeVoice(accepts=False), memory=FakeMemory([QUESTION]))
    async with rig.running():
        await rig.bring_up_a_question()
    assert rig.overlay.sent == [QUESTION]
    assert rig.spoken == []


async def test_with_nowhere_to_get_questions_it_stays_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    async with rig.running():
        await rig.bring_up_a_question()
    assert rig.overlay.sent == []
    assert rig.voice.said == ["Brain connected."]
    assert "Director action failed" not in caplog.text


async def test_the_directors_own_ticker_brings_up_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("brain.director.director.TICK_INTERVAL_S", 0.001)
    # With no gap between questions, a tick that lands on the greeting only delays the next try.
    rig = Rig(memory=FakeMemory([QUESTION]), quiet_s=0.0, gap_s=0.0)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0))
        for _ in range(200):
            if rig.overlay.sent:
                break
            await asyncio.sleep(0.001)
    assert rig.overlay.sent == [QUESTION]


async def test_a_bark_with_no_bank_yet_falls_back_to_the_talker() -> None:
    talker = FakeTextLLM(["That looks rough."])
    rig = Rig(talker=talker, bark_events=BARKS)
    async with rig.running():
        await rig.publish(GameEvent("danger_started", {"threats": ["Big Slime"]}))
    assert rig.voice.played == []
    assert rig.voice.said == ["That looks rough."]
    assert rig.spoken == ["That looks rough."]
    assert "danger started" in talker.prompts[0] and "Big Slime" in talker.prompts[0]


async def test_a_bark_is_skipped_while_the_slot_is_busy() -> None:
    stuck = Stuck("Reply.")
    talker = FakeTextLLM(["Reaction."])
    rig = Rig(talker=talker, agent=ScriptedToolLLM([stuck]), bark_events=BARKS)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert not stuck.cancelled
        stuck.gate.set()
        await settle()
    assert talker.prompts == []
    assert rig.voice.said == ["Reply."]


async def test_a_barge_in_cancels_a_bark() -> None:
    gate = asyncio.Event()
    talker = FakeTextLLM(["Stale reaction."], gate=gate)
    rig = Rig(talker=talker, bark_events=BARKS)
    async with rig.running():
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert len(talker.prompts) == 1
        await rig.publish(PlayerStartedSpeaking())
        gate.set()
        await settle()
    assert rig.voice.said == []


@pytest.mark.parametrize(("proactive", "line"), [(True, HINTS_ON), (False, HINTS_OFF)])
async def test_hints_change_the_prompt_but_not_whether_it_talks(proactive: bool, line: str) -> None:
    talker = FakeTextLLM(["Reaction."])
    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(talker=talker, agent=agent, proactive=proactive)
    async with rig.running():
        await rig.publish(GameEvent("something", ts=100.0))
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert rig.voice.said == ["Reaction.", "Reply."]
    assert line in talker.system and line in agent.system


async def test_replies_and_reactions_use_the_personalitys_tone() -> None:
    talker = FakeTextLLM(["Reaction."])
    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(talker=talker, agent=agent)
    async with rig.running():
        await rig.publish(GameEvent("something", ts=100.0))
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert TONE in talker.system and TONE in agent.system


async def test_a_player_turn_gets_the_live_context() -> None:
    queries: list[str] = []

    async def context(query: str) -> str:
        queries.append(query)
        return "NOW: danger: high"

    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(agent=agent, context=context)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert queries == ["hello"]
    assert "NOW: danger: high" in agent.system


async def test_a_context_failure_still_answers_the_player(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken(_query: str) -> str:
        raise RuntimeError("database locked")

    rig = Rig(agent=ScriptedToolLLM([ToolStep("Reply.")]), context=broken)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert rig.voice.said == ["Reply."]
    assert "Couldn't build the talker's context" in caplog.text
