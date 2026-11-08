"""Pausing: the partner says nothing but keeps listening, then asks what it wants to learn."""

import asyncio

import pytest
from pydantic import BaseModel

from brain.agent.tools import Tool, TurnContext
from brain.director import director as director_module
from brain.director.rules import (
    AskQuestion,
    AskTalker,
    DirectorState,
    PlayBark,
    Say,
    SetVoice,
    StopSpeaking,
    decide,
)
from brain.events import (
    GameEvent,
    OverlayConnected,
    PlayerSpeech,
    SettingsChanged,
    Tick,
    VoicePreviewRequested,
)
from brain.llm.base import ToolCall, ToolStep
from brain.tests.director_rig import GAP_S, LOOKING, QUIET_S, Rig, settle, until
from brain.tests.fakes import FakeMemory, ScriptedToolLLM
from shared.protocol.messages import QuestionAsk, Settings

QUESTION = QuestionAsk(question_id="7", text="Where's your base?", options=[])
PAUSED = Settings(paused=True)
RUNNING = Settings()


def connected(at: float = 0.0) -> DirectorState:
    state = DirectorState(
        question_quiet_s=QUIET_S,
        question_gap_s=GAP_S,
        advice_gap_s=0,
        bark_events={"danger_started": "danger"},
    )
    decide(OverlayConnected(display_scale=1.0, ts=at), state)
    return state


def change(settings: Settings, state: DirectorState, ts: float = 0.0) -> list[object]:
    return list(decide(SettingsChanged(settings=settings, ts=ts), state))


def test_pausing_stops_speech_once() -> None:
    state = connected()
    assert change(PAUSED, state) == [SetVoice(None), StopSpeaking()]
    # Another setting changed while paused: nothing left to stop.
    assert change(Settings(paused=True, personality="calm"), state) == [SetVoice(None)]


def test_while_paused_nothing_starts_speech_but_the_player_is_still_heard() -> None:
    state = connected()
    change(PAUSED, state, ts=1.0)
    assert decide(PlayerSpeech(transcript="what's that?", ts=50.0), state) == []
    assert state.last_talk_at == 50.0
    assert decide(GameEvent(name="danger_started", ts=60.0), state) == []
    assert state.in_danger  # Still tracked, so unpausing mid-fight waits.
    assert decide(Tick(ts=500.0), state) == []


def test_a_voice_preview_still_plays_while_paused() -> None:
    # The player asked for it, so it's not the partner choosing to talk.
    state = connected()
    change(PAUSED, state)
    assert decide(VoicePreviewRequested(text="Hi there.", ts=5.0), state) == [Say("Hi there.")]


def test_no_greeting_while_paused() -> None:
    state = DirectorState()
    change(PAUSED, state)
    assert decide(OverlayConnected(display_scale=1.0, ts=0.0), state) == []


def test_unpausing_asks_at_the_next_tick_without_waiting_for_quiet_or_the_gap() -> None:
    state = connected()
    assert decide(Tick(ts=QUIET_S), state) == [AskQuestion()]
    change(PAUSED, state, ts=QUIET_S + 1)
    decide(PlayerSpeech(transcript="hang on", ts=QUIET_S + 2), state)
    change(RUNNING, state, ts=QUIET_S + 3)
    # Well inside both the quiet stretch and the gap since the last question.
    assert decide(Tick(ts=QUIET_S + 5), state) == [AskQuestion()]
    # Only the first: after that the usual budget applies again.
    assert decide(Tick(ts=QUIET_S + 10), state) == []


def test_unpausing_mid_fight_waits_for_it_to_end() -> None:
    state = connected()
    change(PAUSED, state)
    decide(GameEvent(name="danger_started", ts=1.0), state)
    change(RUNNING, state, ts=2.0)
    assert decide(Tick(ts=5.0), state) == []
    decide(GameEvent(name="danger_ended", ts=6.0), state)
    assert decide(Tick(ts=10.0), state) == [AskQuestion()]


def test_unpaused_turns_and_events_work_as_before() -> None:
    state = connected()
    change(PAUSED, state)
    change(RUNNING, state)
    assert decide(PlayerSpeech(transcript="hi", ts=1.0), state) == [AskTalker("hi", None)]
    actions = decide(GameEvent(name="danger_started", ts=30.0), state)
    assert actions == [PlayBark("danger", "danger_started", {}, ts=30.0)]


class NoInput(BaseModel):
    pass


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(director_module, "SPEAK_RETRY_S", 0.001)
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 0.05)


async def test_pausing_cancels_a_check_and_the_turn_queued_behind_it() -> None:
    gate = asyncio.Event()
    cancelled = asyncio.Event()

    async def check(_arguments: NoInput, _turn: TurnContext) -> str:
        try:
            await gate.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "a man in brown"

    agent = ScriptedToolLLM(
        [ToolStep("", (ToolCall("check", {}),)), ToolStep("The Guide."), ToolStep("Later.")]
    )
    rig = Rig(agent=agent, tools=[Tool("check", "Checks the screen.", NoInput, check)])
    async with rig.running():
        await rig.publish(PlayerSpeech(transcript="what's next to me?"))
        await rig.publish(PlayerSpeech(transcript="and then?"))
        assert rig.director.checking

        await rig.publish(SettingsChanged(settings=PAUSED))
        await until(cancelled.is_set)
        gate.set()
        await settle()
    assert rig.voice.said == [LOOKING]
    assert agent.sends == ["what's next to me?"]
    assert not rig.director.checking


async def test_a_question_cut_off_by_pausing_goes_back_and_is_asked_on_unpause() -> None:
    memory = FakeMemory([QUESTION, QUESTION])
    rig = Rig(memory=memory)
    rig.voice.accepts = False  # The player is talking, so the question waits to be said.
    async with rig.running():
        await rig.bring_up_a_question()
        assert memory.questions_taken == 1
        await rig.publish(SettingsChanged(settings=PAUSED, ts=rig.now + 1))
        await until(lambda: memory.released == [QUESTION.question_id])

        rig.voice.accepts = True
        await rig.publish(SettingsChanged(settings=RUNNING, ts=rig.now + 1))
        await rig.publish(Tick(ts=rig.now + 5))
        await until(lambda: rig.spoken == [QUESTION.text])
