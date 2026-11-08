"""Questions are spoken, never shown, and one that's never heard goes back in memory's queue."""

import asyncio

import pytest

from brain.director import director as director_module
from brain.events import OverlayConnected, PlayerSpeech, PlayerStartedSpeaking, Tick
from brain.llm.base import ToolStep
from brain.tests.director_rig import QUIET_S, Rig, Stuck, settle, until
from brain.tests.fakes import FakeMemory, FakeVoice, ScriptedToolLLM
from shared.protocol.messages import QuestionAsk

QUESTION = QuestionAsk(question_id="7", text="Where's your base?", options=["East", "West"])
GREETING = "Brain connected."


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(director_module, "SPEAK_RETRY_S", 0.001)
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 0.05)


async def test_a_question_is_spoken_and_never_shown() -> None:
    memory = FakeMemory([QUESTION])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
    # A popup pulled the player's eyes off the game.
    assert not any(isinstance(message, QuestionAsk) for message in rig.overlay.sent)
    assert rig.voice.said == [GREETING, QUESTION.text]
    assert rig.spoken == [QUESTION.text]
    assert memory.questions_taken == 1 and memory.released == []


async def test_no_open_question_stays_quiet() -> None:
    memory = FakeMemory([])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
    assert memory.questions_taken == 1  # It did ask memory, and memory had nothing.
    assert rig.voice.said == [GREETING] and rig.spoken == []
    assert memory.released == []


async def test_with_nowhere_to_get_questions_it_stays_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    async with rig.running():
        await rig.bring_up_a_question()
    assert rig.voice.said == [GREETING]
    assert "Director action failed" not in caplog.text


async def test_the_directors_own_ticker_brings_up_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(director_module, "TICK_INTERVAL_S", 0.001)
    # With no gap between questions, a tick that lands on the greeting only delays the next try.
    rig = Rig(memory=FakeMemory([QUESTION]), quiet_s=0.0, gap_s=0.0)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0))
        await until(lambda: QUESTION.text in rig.spoken)


async def test_a_question_waits_for_the_player_to_stop_talking() -> None:
    memory = FakeMemory([QUESTION])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0, ts=100.0))
        rig.voice.accepts = False
        await rig.publish(Tick(ts=100.0 + QUIET_S))
        await until(lambda: QUESTION.text in rig.voice.said)
        rig.voice.accepts = True
        await until(lambda: rig.spoken == [QUESTION.text])
    assert memory.released == []


async def test_a_question_never_said_goes_back_in_the_queue() -> None:
    memory = FakeMemory([QUESTION])
    rig = Rig(voice=FakeVoice(accepts=False), memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
        await until(lambda: memory.released == [QUESTION.question_id])
    assert QUESTION.text in rig.voice.said  # It was tried,
    assert rig.spoken == []  # but never heard.


async def test_a_barge_in_before_the_question_is_heard_puts_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 60.0)
    memory = FakeMemory([QUESTION])
    rig = Rig(memory=memory)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0, ts=100.0))
        rig.voice.accepts = False
        await rig.publish(Tick(ts=100.0 + QUIET_S))
        await until(lambda: QUESTION.text in rig.voice.said)
        await rig.publish(PlayerStartedSpeaking())
        await until(lambda: memory.released == [QUESTION.question_id])
    assert rig.spoken == []


async def test_a_failed_release_is_logged_and_the_loop_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenMemory(FakeMemory):
        async def release_question(self, question_id: str) -> None:
            raise RuntimeError("database locked")

    memory = BrokenMemory([QUESTION])
    rig = Rig(voice=FakeVoice(accepts=False), memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
        await until(lambda: "Couldn't put question 7 back in the queue" in caplog.text)


async def test_ticks_while_the_slot_is_busy_spend_no_question_budget() -> None:
    stuck = Stuck("Reply.")
    memory = FakeMemory([QUESTION])
    rig = Rig(agent=ScriptedToolLLM([stuck]), memory=memory)
    async with rig.running():
        await rig.publish(OverlayConnected(display_scale=1.0, ts=100.0))
        await rig.publish(PlayerSpeech(transcript="hello", ts=100.0))
        await rig.publish(Tick(ts=100.0 + QUIET_S))
        assert memory.questions_taken == 0
        stuck.gate.set()
        await settle()
        # The reply was just said, so the next question waits a quiet stretch, not a whole gap.
        await rig.publish(Tick(ts=100.0 + QUIET_S * 2))
    assert rig.spoken == ["Reply.", QUESTION.text]


class RefusesQuestions(FakeVoice):
    """Acts as if the player is talking whenever the question comes up, and only then."""

    async def say(self, text: str) -> bool:
        await super().say(text)
        return text != QUESTION.text


async def test_a_question_cut_off_by_a_player_turn_goes_back_and_the_turn_is_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 60.0)
    memory = FakeMemory([QUESTION])
    agent = ScriptedToolLLM([ToolStep("Reply.")])
    rig = Rig(voice=RefusesQuestions(), agent=agent, memory=memory)
    async with rig.running():
        await rig.bring_up_a_question()
        await until(lambda: QUESTION.text in rig.voice.said)
        # Typed turns arrive like this too, so this isn't only about speech.
        await rig.publish(PlayerSpeech(transcript="hello", ts=125.0))
        await until(lambda: memory.released == [QUESTION.question_id])
        await until(lambda: rig.spoken == ["Reply."])
        await asyncio.sleep(0)
    assert agent.sends == ["hello"]
