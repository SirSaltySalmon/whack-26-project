"""answer_question, remember_fact and forget_fact: how a player turn sets memory straight."""

import pytest

from brain.agent.memory_tools import MAX_VALUE_CHARS, PLAYER_CONFIDENCE
from brain.memory.models import RememberResult
from brain.tests.agent_rig import rig
from brain.tests.fakes import FakeMemory


async def test_an_answer_to_the_question_just_asked_goes_to_memory() -> None:
    r = rig()
    output = await r.run("answer_question", question_id=0, answer="Near spawn", correction="")
    assert r.memory.answered == [(None, "Near spawn", None)]
    assert output == "Saved their answer."


async def test_a_no_with_a_correction_names_the_question_and_says_whats_true() -> None:
    r = rig()
    await r.run("answer_question", question_id=12, answer=" No ", correction=" The Eye ")
    assert r.memory.answered == [(12, "No", "The Eye")]


async def test_an_answer_with_no_question_waiting_says_nothing_was_saved() -> None:
    class NothingAsked(FakeMemory):
        async def answer_question(
            self, question_id: int | None, answer: str, correction: str | None = None
        ) -> RememberResult | None:
            await super().answer_question(question_id, answer, correction)
            return None

    r = rig(memory=NothingAsked())
    output = await r.run("answer_question", question_id=0, answer="Yes", correction="")
    assert "nothing was saved" in output


async def test_a_negative_question_id_never_reaches_memory() -> None:
    r = rig()
    output = await r.run("answer_question", question_id=-1, answer="Yes", correction="")
    assert output == "answer_question was given invalid arguments."
    assert r.memory.answered == []


async def test_a_correction_is_remembered_as_the_players_word() -> None:
    r = rig()
    output = await r.run(
        "remember_fact", subject="playthrough", attribute="progress", value="beat Skeletron"
    )
    assert r.memory.remembered == [
        ("playthrough", "progress", "beat Skeletron", "player", PLAYER_CONFIDENCE)
    ]
    assert r.memory.tentative_remembered == []
    assert output == "Remembered."


async def test_a_rambling_value_is_cut_to_a_size_memory_can_show() -> None:
    r = rig()
    await r.run("remember_fact", subject="player", attribute="goal", value="x" * 1000)
    assert len(r.memory.remembered[0][2]) == MAX_VALUE_CHARS


@pytest.mark.parametrize(
    ("subject", "attribute", "value"),
    [(" ", "goal", "win"), ("player", "", "win"), ("player", "goal", "  ")],
    ids=["no_subject", "no_attribute", "no_value"],
)
async def test_a_fact_with_a_blank_part_isnt_stored(
    subject: str, attribute: str, value: str
) -> None:
    r = rig()
    output = await r.run("remember_fact", subject=subject, attribute=attribute, value=value)
    assert r.memory.remembered == [] and "needs" in output


async def test_a_fact_memory_cant_settle_is_reported_as_noted_not_remembered() -> None:
    class Conflicted(FakeMemory):
        async def remember(self, *args: object, **kwargs: object) -> RememberResult:
            return RememberResult("conflict")

    r = rig(memory=Conflicted())
    output = await r.run("remember_fact", subject="player", attribute="class", value="mage")
    assert output.startswith("Noted, but")


async def test_forgetting_a_remembered_fact_says_so() -> None:
    r = rig()
    await r.memory.remember("player", "class", "mage", "observed", 0.6)
    assert await r.run("forget_fact", subject="player", attribute="class") == "Forgotten."
    assert r.memory.forgotten == [("player", "class")]


async def test_forgetting_something_never_remembered_says_there_was_nothing() -> None:
    r = rig()
    output = await r.run("forget_fact", subject="player", attribute="class")
    assert r.memory.forgotten == [("player", "class")]
    assert "nothing to forget" in output


async def test_a_memory_failure_becomes_text() -> None:
    class Broken(FakeMemory):
        async def forget(self, subject: str, attribute: str) -> int:
            raise RuntimeError("database locked")

    r = rig(memory=Broken())
    output = await r.run("forget_fact", subject="player", attribute="class")
    assert output == "forget_fact failed."
