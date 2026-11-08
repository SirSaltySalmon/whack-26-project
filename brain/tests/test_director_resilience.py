"""A bug in one rule must cost one reaction, not the whole partner."""

import pytest

from brain.director import director as director_module
from brain.director.rules import Action, DirectorState
from brain.events import Event, GameEvent, PlayerSpeech
from brain.llm.base import ToolStep
from brain.tests.director_rig import Rig
from brain.tests.fakes import ScriptedToolLLM


async def test_a_rule_that_raises_is_logged_and_the_next_event_still_answered(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_decide = director_module.decide

    def flaky_decide(event: Event, state: DirectorState) -> list[Action]:
        if isinstance(event, GameEvent):
            raise RuntimeError("a rule bug")
        return real_decide(event, state)

    monkeypatch.setattr(director_module, "decide", flaky_decide)
    rig = Rig(agent=ScriptedToolLLM([ToolStep("Still here.")]))
    async with rig.running():  # Fails the test if the loop stopped
        await rig.publish(GameEvent("boss_spawned"))
        await rig.publish(PlayerSpeech(transcript="you there?"))
    assert "Director failed to handle GameEvent" in caplog.text
    assert rig.voice.said == ["Still here."]
