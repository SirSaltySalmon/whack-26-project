"""What the director says besides plain replies: barks, and how settings shape it.

Questions are in test_director_questions.py, and tips in test_director_advice.py.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.director.personalities import Personality, PersonalityBook
from brain.director.talker import HINTS_OFF, HINTS_ON
from brain.events import (
    GameEvent,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
)
from brain.llm.base import ToolCall, ToolStep
from brain.tests.director_rig import DONE, LOOKING, TONE, Rig, Stuck, settle, until
from brain.tests.fakes import (
    FakeBarkSynth,
    FakeTextLLM,
    FakeVoice,
    ScriptedToolLLM,
)
from brain.voice.barks import BarkBank
from shared.protocol.messages import Settings as OverlaySettings

BARKS = {"danger_started": "danger"}


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


BARK_BOOK = PersonalityBook(
    default="calm",
    personalities={
        "calm": Personality(
            tone=TONE,
            lines={"looking": [LOOKING], "done": [DONE], "danger": ["Heads up."]},
        )
    },
)


async def _ready_bank(tmp_path: Path, voice: str = "voiceA") -> BarkBank:
    bank = BarkBank(BARK_BOOK, FakeBarkSynth(), tmp_path, "model", 24000)
    await bank.prepare(voice)
    return bank


async def test_a_ready_bark_plays_without_the_talker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    talker = FakeTextLLM(["Should not be used."])
    bank = await _ready_bank(tmp_path)
    rig = Rig(talker=talker, bark_events=BARKS, barks=bank, voice_id="voiceA")
    async with rig.running():
        await rig.publish(GameEvent("danger_started"))
    assert [bark.text for bark in rig.voice.played] == ["Heads up."]
    assert rig.voice.said == [] and talker.prompts == []
    assert rig.spoken == ["Heads up."]
    assert "Latency: event to bark" in caplog.text


async def test_a_dropped_bark_isnt_remembered_as_said(tmp_path: Path) -> None:
    bank = await _ready_bank(tmp_path)
    rig = Rig(voice=FakeVoice(accepts=False), bark_events=BARKS, barks=bank, voice_id="voiceA")
    async with rig.running():
        await rig.publish(GameEvent("danger_started"))
    assert len(rig.voice.played) == 1
    assert rig.spoken == []


async def test_a_bark_for_another_voice_falls_back_to_the_talker(tmp_path: Path) -> None:
    talker = FakeTextLLM(["That looks rough."])
    bank = await _ready_bank(tmp_path, voice="voiceA")
    rig = Rig(talker=talker, bark_events=BARKS, barks=bank, voice_id="voiceB")
    async with rig.running():
        await rig.publish(GameEvent("danger_started"))
    assert rig.voice.played == []
    assert rig.voice.said == ["That looks rough."]


async def test_the_looking_filler_plays_its_bark_when_ready(tmp_path: Path) -> None:
    class NoInput(BaseModel):
        pass

    async def check(_arguments: NoInput, _turn: TurnContext) -> str:
        return "a man in brown"

    bank = await _ready_bank(tmp_path)
    agent = ScriptedToolLLM([ToolStep("", (ToolCall("check", {}),)), ToolStep("Found it.")])
    rig = Rig(
        agent=agent,
        tools=[Tool("check", "Checks the screen.", NoInput, check)],
        barks=bank,
        voice_id="voiceA",
    )
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="what's that"))
    assert [bark.text for bark in rig.voice.played] == [LOOKING]
    assert rig.voice.said == ["Found it."]


async def test_changing_voice_prepares_its_barks(tmp_path: Path) -> None:
    synth = FakeBarkSynth()
    bank = BarkBank(BARK_BOOK, synth, tmp_path, "model", 24000)
    rig = Rig(barks=bank, voice_id="voiceA")
    async with rig.running():
        await rig.publish(SettingsChanged(settings=OverlaySettings(voice_id="voiceB")))
        await until(lambda: bank.get("calm", "danger", 0, "voiceB") is not None)
    assert rig.voice.voice_id == "voiceB"
    assert {call[1] for call in synth.calls} == {"voiceB"}
