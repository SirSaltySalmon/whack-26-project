"""A turn that's checking the screen must still answer when the player talks over it."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from brain.agent.tools import ToolRegistry
from brain.director import director as director_module
from brain.director.director import Director
from brain.director.rules import AskTalker, CancelSpeech
from brain.events import EventBus


class FakeVoice:
    """Refuses to speak while the player is talking, like PipecatVoice."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.player_talking = False

    async def say(self, text: str) -> bool:
        if self.player_talking:
            return False
        self.said.append(text)
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        return None

    async def run(self) -> None:
        return None

    def live_state(self) -> dict[str, str]:
        return {}


def director(voice: FakeVoice) -> Director:
    built = Director(
        EventBus(),
        voice,
        proactive=lambda: True,
        agent=object(),  # type: ignore[arg-type]
        tools=ToolRegistry([]),
    )
    return built


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(director_module, "SPEAK_RETRY_S", 0.01)


def fake_turn(
    checked: asyncio.Event, release: asyncio.Event, answer: str = "It's the Guide."
) -> Callable[..., Awaitable[str]]:
    async def run_turn(*args: object, **kwargs: object) -> str:
        looking = args[8]
        await looking()  # type: ignore[operator]
        checked.set()
        await release.wait()
        return answer

    return run_turn


async def test_talking_during_a_check_does_not_cancel_it(monkeypatch: pytest.MonkeyPatch) -> None:
    checked, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(director_module, "run_turn", fake_turn(checked, release))
    voice = FakeVoice()
    built = director(voice)

    built._dispatch(AskTalker("what's next to me?", None))
    await checked.wait()
    assert built.checking

    voice.player_talking = True
    built._dispatch(CancelSpeech())
    release.set()
    await asyncio.sleep(0.05)
    voice.player_talking = False
    assert built._slot is not None
    await built._slot

    assert voice.said[-1] == "It's the Guide."
    assert not built.checking


async def test_a_new_question_waits_for_the_check_to_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked, release = asyncio.Event(), asyncio.Event()
    turns = [fake_turn(checked, release, "It's the Guide.")]

    async def run_turn(*args: object, **kwargs: object) -> str:
        if turns:
            return await turns.pop(0)(*args, **kwargs)
        return "Anything else?"

    monkeypatch.setattr(director_module, "run_turn", run_turn)
    voice = FakeVoice()
    built = director(voice)

    built._dispatch(AskTalker("what's next to me?", None))
    await checked.wait()
    built._dispatch(AskTalker("so, answer?", None))
    release.set()
    assert built._slot is not None
    await built._slot

    answers = [line for line in voice.said if line in ("It's the Guide.", "Anything else?")]
    assert answers == ["It's the Guide.", "Anything else?"]


async def test_a_turn_without_tools_is_still_cancelled_by_talking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def run_turn(*args: object, **kwargs: object) -> str:
        started.set()
        await asyncio.sleep(10)
        return "Too late."

    monkeypatch.setattr(director_module, "run_turn", run_turn)
    voice = FakeVoice()
    built = director(voice)

    built._dispatch(AskTalker("hi", None))
    await started.wait()
    built._dispatch(CancelSpeech())
    assert built._slot is not None
    with pytest.raises(asyncio.CancelledError):
        await built._slot
    assert "Too late." not in voice.said


async def test_an_answer_is_dropped_if_the_player_never_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(director_module, "ANSWER_WAIT_S", 0.05)
    checked, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(director_module, "run_turn", fake_turn(checked, release))
    voice = FakeVoice()
    built = director(voice)

    built._dispatch(AskTalker("what's that?", None))
    await checked.wait()
    voice.player_talking = True
    release.set()
    assert built._slot is not None
    await built._slot

    assert "It's the Guide." not in voice.said
    assert not built.checking
