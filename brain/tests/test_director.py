"""The speech slot: what stays responsive, what gets cancelled, and what gets skipped."""

import asyncio

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.events import (
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
    Tick,
)
from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, ToolCall, ToolStep
from brain.tests.director_rig import DONE, LOOKING, QUIET_S, UNAVAILABLE, Rig, Stuck, settle
from brain.tests.fakes import FakeMemory, FakeTextLLM, FakeVoice, ScriptedToolLLM
from shared.protocol.messages import QuestionAsk, Settings

QUESTION = QuestionAsk(question_id="q1", text="Where's your base?")


class NoInput(BaseModel):
    pass


def wants_tool(name: str) -> ToolStep:
    return ToolStep("", (ToolCall(name, {}),))


async def test_events_keep_being_handled_while_a_player_turn_is_stuck_in_the_model() -> None:
    stuck = Stuck("Late reply.")
    rig = Rig(agent=ScriptedToolLLM([stuck]))
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
        assert stuck.started and rig.voice.said == []

        await rig.publish(SettingsChanged(settings=Settings(voice_id="voice-2")))
        assert rig.voice.voice_id == "voice-2"

        # A setting neither waits for a reply nor cancels it, so the turn still gets to finish.
        stuck.gate.set()
        await settle()
    assert rig.voice.said == ["Late reply."]


async def test_a_barge_in_cancels_the_turn_and_its_stale_reply_is_never_spoken() -> None:
    stuck = Stuck("Stale reply.")
    rig = Rig(agent=ScriptedToolLLM([stuck]))
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
        assert stuck.started
        await rig.publish(PlayerStartedSpeaking())
        assert stuck.cancelled
        # Even if the model's answer turns up now, nothing is left to speak it.
        stuck.gate.set()
        await settle()
    assert rig.voice.said == [] and rig.spoken == []


async def test_a_barge_in_during_a_quick_tool_drops_the_reply() -> None:
    # A slow tool survives a barge-in (test_director_checks.py). A quick one said no filler line,
    # so nothing was promised and the turn is cancelled like one without tools.
    gate = asyncio.Event()

    async def held(_arguments: NoInput, _turn: TurnContext) -> str:
        await gate.wait()
        return "tool output"

    agent = ScriptedToolLLM([wants_tool("held"), ToolStep("Stale reply.")])
    rig = Rig(agent=agent, tools=[Tool("held", "Normally instant.", NoInput, held, quick=True)])
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="watch this"))
        assert rig.voice.said == [] and not rig.director.checking
        await rig.publish(PlayerStartedSpeaking())
        gate.set()
        await settle()
    assert agent.results == []  # The model never heard back, so it can't have replied.
    assert rig.voice.said == []


async def test_the_turn_after_a_barge_in_is_answered_and_knows_when_it_began() -> None:
    began: list[float | None] = []

    async def note(_arguments: NoInput, turn: TurnContext) -> str:
        began.append(turn.started_at)
        return "tool output"

    stuck = Stuck("Stale reply.")
    agent = ScriptedToolLLM([stuck, wants_tool("note"), ToolStep("Fresh reply.")])
    rig = Rig(agent=agent, tools=[Tool("note", "Notes the turn.", NoInput, note)])
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="first"))
        await rig.publish(PlayerStartedSpeaking(ts=42.0))
        await rig.publish(PlayerSpeech(transcript="second"))
    assert began == [42.0]
    assert rig.voice.said == [LOOKING, "Fresh reply."]
    assert rig.spoken == ["Fresh reply."]  # Only the reply is remembered, not the filler.


async def test_a_new_player_turn_replaces_one_in_progress() -> None:
    first = Stuck("Stale reply.")
    agent = ScriptedToolLLM([first, ToolStep("Second reply.")])
    rig = Rig(agent=agent)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="first"))
        await rig.publish(PlayerSpeech(transcript="second"))
        assert first.cancelled
        first.gate.set()
        await settle()
    assert agent.sends == ["first", "second"]
    assert rig.voice.said == ["Second reply."]


async def test_a_player_turn_replaces_a_reaction_in_progress() -> None:
    gate = asyncio.Event()
    talker = FakeTextLLM(["Stale reaction."], gate=gate)
    rig = Rig(talker=talker, agent=ScriptedToolLLM([ToolStep("Reply.")]))
    async with rig.running():
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert len(talker.prompts) == 1 and rig.voice.said == []
        await rig.publish(PlayerSpeech(transcript="hello"))
        gate.set()
        await settle()
    assert rig.voice.said == ["Reply."]


async def test_event_reactions_are_skipped_while_the_slot_is_busy() -> None:
    stuck = Stuck("Reply.")
    talker = FakeTextLLM(["Reaction."])
    rig = Rig(talker=talker, agent=ScriptedToolLLM([stuck]))
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert talker.prompts == [] and not stuck.cancelled

        stuck.gate.set()
        await settle()
        # Skipped rather than queued: it doesn't turn up once the slot is free.
        assert talker.prompts == [] and rig.voice.said == ["Reply."]

        await rig.publish(GameEvent("danger_ended", ts=200.0))
    assert rig.voice.said == ["Reply.", "Reaction."]


async def test_questions_are_skipped_while_the_slot_is_busy_and_stay_open() -> None:
    stuck = Stuck("Reply.")
    memory = FakeMemory([QUESTION])
    rig = Rig(agent=ScriptedToolLLM([stuck]), memory=memory)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0, ts=100.0))
        await rig.publish(PlayerSpeech(transcript="hello", ts=100.0))
        assert stuck.started
        await rig.publish(Tick(ts=100.0 + QUIET_S))
    # Taking a question marks it asked, so one that's skipped must not have been taken.
    assert memory.questions_taken == 0 and rig.overlay.sent == []


async def test_a_failed_reaction_doesnt_stop_the_loop(caplog: pytest.LogCaptureFixture) -> None:
    talker = FakeTextLLM(error=RuntimeError("vendor broke"))
    rig = Rig(talker=talker)
    async with rig.running():
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert rig.voice.said == [] and "Director action failed" in caplog.text

        talker.error, talker.chunks = None, ["Back again."]
        await rig.publish(GameEvent("danger_ended", ts=200.0))
    assert rig.voice.said == ["Back again."]


class FailingVoice(FakeVoice):
    """Refuses its first line and every voice change, as a lost audio device would."""

    async def say(self, text: str) -> bool:
        await super().say(text)
        if len(self.said) == 1:
            raise OSError("no audio device")
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        raise OSError("no audio device")


async def test_a_failing_voice_doesnt_stop_the_loop(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig(voice=FailingVoice(), talker=FakeTextLLM(["Reaction."]))
    async with rig.running():
        await rig.publish(SettingsChanged(settings=Settings(voice_id="voice-2")))
        await rig.publish(GameEvent("danger_started", ts=100.0))
        await rig.publish(GameEvent("danger_ended", ts=200.0))
    assert rig.voice.said == ["Reaction.", "Reaction."]
    assert rig.spoken == ["Reaction."]  # The line that raised was never really said.
    assert caplog.text.count("Director action failed") == 2


@pytest.mark.parametrize(
    "error",
    [LLMUnavailableError("over quota"), LLMEmptyResponseError("blocked"), RuntimeError("broke")],
    ids=["over_quota", "empty", "vendor_error"],
)
async def test_a_player_turn_that_fails_still_gets_an_answer(error: Exception) -> None:
    rig = Rig(agent=ScriptedToolLLM([error]))
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert rig.voice.said == [UNAVAILABLE]


async def test_a_model_failure_after_a_tool_says_the_done_line() -> None:
    # The player may already be looking at the result, so "I can't" would be wrong here.
    async def quick(_arguments: NoInput, _turn: TurnContext) -> str:
        return "tool output"

    agent = ScriptedToolLLM([wants_tool("quick"), LLMUnavailableError("over quota")])
    rig = Rig(agent=agent, tools=[Tool("quick", "Returns at once.", NoInput, quick)])
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="look"))
    assert rig.voice.said == [LOOKING, DONE]


async def test_a_turn_with_nothing_to_say_stays_quiet_and_logs_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(agent=ScriptedToolLLM([ToolStep("")]))
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert rig.voice.said == [] and "produced no reply" in caplog.text


@pytest.mark.parametrize("accepts", [True, False], ids=["accepted", "dropped"])
async def test_on_spoken_only_hears_lines_the_voice_accepted(accepts: bool) -> None:
    rig = Rig(
        voice=FakeVoice(accepts=accepts),
        talker=FakeTextLLM(["Reaction."]),
        agent=ScriptedToolLLM([ToolStep("Reply.")]),
        memory=FakeMemory([QUESTION]),
    )
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
        await rig.publish(GameEvent("something", ts=50.0))
        await rig.bring_up_a_question()
    assert rig.voice.said == ["Reply.", "Reaction.", "Brain connected.", QUESTION.text]
    assert rig.spoken == (["Reply.", "Reaction.", QUESTION.text] if accepts else [])


async def test_shutting_down_cancels_speech_in_progress() -> None:
    stuck = Stuck("Late reply.")
    rig = Rig(agent=ScriptedToolLLM([stuck]))
    task = asyncio.create_task(rig.director.run())
    await rig.publish(PlayerSpeech(transcript="hello"))
    assert stuck.started

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await settle()
    assert stuck.cancelled and rig.voice.said == []


async def test_the_open_page_excerpt_reaches_player_turns_and_never_reactions() -> None:
    asked: list[str] = []

    def excerpt(transcript: str) -> str:
        asked.append(transcript)
        return "OPEN PAGE (test): Skeletron\nIt drops a mask."

    talker = FakeTextLLM(["Reaction."])
    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(talker=talker, agent=agent, page_excerpt=excerpt)
    async with rig.running():
        await rig.publish(GameEvent("danger_started", ts=100.0))
        assert rig.voice.said == ["Reaction."]
        assert "It drops a mask." not in talker.system and asked == []

        await rig.publish(PlayerSpeech(transcript="what does it drop?"))
    assert rig.voice.said == ["Reaction.", "Reply."]
    assert asked == ["what does it drop?"]
    assert "OPEN PAGE (test): Skeletron\nIt drops a mask." in agent.system


async def test_a_failing_excerpt_does_not_cost_the_player_their_reply() -> None:
    def broken(_transcript: str) -> str:
        raise RuntimeError("bad page")

    rig = Rig(agent=ScriptedToolLLM([ToolStep("Reply.")]), page_excerpt=broken)
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="hello"))
    assert rig.voice.said == ["Reply."]
