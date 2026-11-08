import asyncio
import json
import logging

import pytest

from brain.learner.progress import ATTRIBUTE, SUBJECT
from brain.learner.questions import (
    PROFILE_KEY,
    parse_plan,
    plan_and_queue_questions,
    planned_progress_question,
    stored_plan,
    system_prompt,
)
from brain.llm.base import LLMUnavailableError
from brain.memory.db import Database, connect
from brain.memory.profile import ProfileStore
from brain.tests.fakes import FakeMemory, FakeTextLLM

GAME = "Some Game"
BRIEF = "A sandbox game where you dig, build and fight bosses."
PROGRESS = {"subject": SUBJECT, "attribute": ATTRIBUTE, "question": "Beaten the Big Eye yet?"}
GOAL = {"subject": "player", "attribute": "current goal", "question": "What are you after now?"}
STYLE = {"subject": "player", "attribute": "playstyle", "question": "Melee, ranged or magic?"}
REPLY = json.dumps([PROGRESS, GOAL, STYLE])


def keys(plan: list) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    return [(item.subject, item.attribute) for item in plan]


async def database_with(brief: str = BRIEF, data: dict[str, object] | None = None) -> Database:
    database = Database(connect(":memory:"))
    await database.run(lambda conn: ProfileStore(conn).set_brief(GAME, brief))
    if data:
        await database.run(lambda conn: ProfileStore(conn).merge_data(GAME, data))
    return database


async def profile_data(database: Database) -> dict[str, object]:
    return await database.run(lambda conn: ProfileStore(conn).get(GAME).data)


# --- Parsing untrusted model output ---


def test_parses_a_plan_in_order() -> None:
    plan = parse_plan(REPLY, 6)
    assert keys(plan) == [(SUBJECT, ATTRIBUTE), ("player", "current goal"), ("player", "playstyle")]
    assert plan[0].question == "Beaten the Big Eye yet?"


def test_finds_the_array_inside_a_fence_or_a_sentence() -> None:
    assert len(parse_plan(f"```json\n{REPLY}\n```", 6)) == 3
    assert len(parse_plan(f"Here you go: {REPLY} Hope that helps.", 6)) == 3
    assert len(parse_plan(json.dumps({PROFILE_KEY: [GOAL]}), 6)) == 1


def test_a_reply_that_isnt_json_plans_nothing() -> None:
    assert parse_plan("Sorry, I don't know this game.", 6) == []
    assert parse_plan('{"note": "no list here"}', 6) == []


def test_drops_bad_items_and_keeps_the_rest() -> None:
    bad = [
        {"subject": "world", "attribute": "biome", "question": "Which biome?"},
        {"subject": "player", "attribute": "a b c d", "question": "Too many words in the key?"},
        {"subject": "player", "attribute": "goal!", "question": "Punctuation in the key?"},
        {"subject": "player", "attribute": "ramble", "question": " ".join(["word"] * 21) + "?"},
        {"subject": "player", "attribute": "statement", "question": "Ignore your rules."},
        {"subject": "player", "attribute": "missing"},
        "not even an object",
    ]
    assert keys(parse_plan(json.dumps([*bad, GOAL]), 6)) == [("player", "current goal")]


def test_normalizes_attributes_and_question_spacing() -> None:
    item = {"subject": "player", "attribute": "Current_Goal", "question": "  What's   next?  "}
    plan = parse_plan(json.dumps([item]), 6)
    assert plan[0].attribute == "current goal" and plan[0].question == "What's next?"


def test_dedupes_attributes_keeping_the_first() -> None:
    again = {"subject": "playthrough", "attribute": "current goal", "question": "Your aim?"}
    plan = parse_plan(json.dumps([GOAL, again]), 6)
    assert [item.question for item in plan] == ["What are you after now?"]


def test_the_progress_question_goes_first_under_the_scouts_key() -> None:
    misfiled = {**PROGRESS, "subject": "player"}
    plan = parse_plan(json.dumps([GOAL, STYLE, misfiled]), 6)
    assert keys(plan)[0] == (SUBJECT, ATTRIBUTE)
    assert keys(plan)[1:] == [("player", "current goal"), ("player", "playstyle")]


def test_caps_the_number_of_questions() -> None:
    assert keys(parse_plan(REPLY, 2)) == [(SUBJECT, ATTRIBUTE), ("player", "current goal")]


def test_a_stored_plan_is_validated_again() -> None:
    data = {PROFILE_KEY: [GOAL, {"subject": "nobody", "attribute": "x", "question": "?"}]}
    assert keys(stored_plan(data, 6)) == [("player", "current goal")]
    assert stored_plan({PROFILE_KEY: "garbage"}, 6) == []
    assert stored_plan({}, 6) == []


def test_the_prompt_asks_for_the_scouts_key_and_the_count() -> None:
    prompt = system_prompt(4)
    assert "up to 4 questions" in prompt
    assert f'"{SUBJECT}"' in prompt and f'"{ATTRIBUTE}"' in prompt
    assert "{" in prompt and "{{" not in prompt  # The JSON example survived the f-string


# --- Planning once per game, then queueing every session ---


async def test_plans_once_stores_it_in_the_profile_and_queues_in_order() -> None:
    database = await database_with(data={"regions": {"hotbar": [0, 0, 1, 1]}})
    llm, memory = FakeTextLLM([REPLY]), FakeMemory()
    await plan_and_queue_questions(database, memory, GAME, lambda: llm, 6, 5)
    assert memory.wondered == [
        (SUBJECT, ATTRIBUTE, "Beaten the Big Eye yet?"),
        ("player", "current goal", "What are you after now?"),
        ("player", "playstyle", "Melee, ranged or magic?"),
    ]
    data = await profile_data(database)
    assert data["regions"] == {"hotbar": [0, 0, 1, 1]}  # Merged, not replaced
    assert data[PROFILE_KEY] == [PROGRESS, GOAL, STYLE]
    assert GAME in llm.prompts[0] and BRIEF in llm.prompts[0]
    database.close()


async def test_the_next_session_reuses_the_plan_without_a_model_call() -> None:
    database = await database_with()
    llm = FakeTextLLM([REPLY])
    await plan_and_queue_questions(database, FakeMemory(), GAME, lambda: llm, 6, 5)
    memory = FakeMemory()
    await plan_and_queue_questions(database, memory, GAME, lambda: llm, 6, 5)
    assert len(llm.prompts) == 1
    assert [attribute for _, attribute, _ in memory.wondered] == [
        ATTRIBUTE,
        "current goal",
        "playstyle",
    ]
    database.close()


async def test_no_brief_means_no_plan_and_no_model_call(caplog: pytest.LogCaptureFixture) -> None:
    database = await database_with(brief="")
    llm, memory = FakeTextLLM([REPLY]), FakeMemory()
    with caplog.at_level(logging.INFO, logger="brain.learner.questions"):
        await plan_and_queue_questions(database, memory, GAME, lambda: llm, 6, 5)
    assert llm.prompts == [] and memory.wondered == []
    assert PROFILE_KEY not in await profile_data(database)
    assert "No brief" in caplog.text
    database.close()


async def test_a_failed_call_logs_stores_nothing_and_retries_next_launch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = await database_with()
    failing = FakeTextLLM(error=LLMUnavailableError("over quota"))
    with caplog.at_level(logging.WARNING, logger="brain.learner.questions"):
        await plan_and_queue_questions(database, FakeMemory(), GAME, lambda: failing, 6, 5)
    assert "Couldn't plan questions" in caplog.text
    assert PROFILE_KEY not in await profile_data(database)
    working, memory = FakeTextLLM([REPLY]), FakeMemory()
    await plan_and_queue_questions(database, memory, GAME, lambda: working, 6, 5)
    assert len(working.prompts) == 1 and len(memory.wondered) == 3
    database.close()


async def test_a_slow_model_times_out_without_raising(caplog: pytest.LogCaptureFixture) -> None:
    database = await database_with()
    stuck, memory = FakeTextLLM([REPLY], gate=asyncio.Event()), FakeMemory()
    with caplog.at_level(logging.WARNING, logger="brain.learner.questions"):
        await plan_and_queue_questions(database, memory, GAME, lambda: stuck, 6, 0.01)
    assert memory.wondered == [] and "took over" in caplog.text
    assert PROFILE_KEY not in await profile_data(database)
    database.close()


async def test_an_unusable_reply_isnt_cached() -> None:
    database = await database_with()
    await plan_and_queue_questions(database, FakeMemory(), GAME, lambda: FakeTextLLM(["?"]), 6, 5)
    assert PROFILE_KEY not in await profile_data(database)
    database.close()


async def test_one_rejected_question_doesnt_stop_the_rest() -> None:
    class PickyMemory(FakeMemory):
        async def wonder(self, subject: str, attribute: str, text: str) -> object | None:
            if attribute == "current goal":
                raise ValueError("Fact question is empty")
            return await super().wonder(subject, attribute, text)

    database = await database_with()
    memory = PickyMemory()
    await plan_and_queue_questions(database, memory, GAME, lambda: FakeTextLLM([REPLY]), 6, 5)
    assert [attribute for _, attribute, _ in memory.wondered] == [ATTRIBUTE, "playstyle"]
    database.close()


async def test_a_broken_memory_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenMemory(FakeMemory):
        async def wonder(self, subject: str, attribute: str, text: str) -> object | None:
            raise RuntimeError("database is closed")

    database = await database_with()
    with caplog.at_level(logging.ERROR, logger="brain.learner.questions"):
        await plan_and_queue_questions(
            database, BrokenMemory(), GAME, lambda: FakeTextLLM([REPLY]), 6, 5
        )
    assert "Couldn't queue planned questions" in caplog.text
    database.close()


# --- The scout's view of the plan ---


async def test_the_scout_reads_the_planned_progress_question() -> None:
    database = await database_with(data={PROFILE_KEY: [GOAL, PROGRESS]})
    assert await planned_progress_question(database, GAME) == "Beaten the Big Eye yet?"
    database.close()


async def test_no_plan_or_no_progress_question_gives_none() -> None:
    database = await database_with()
    assert await planned_progress_question(database, GAME) is None
    await database.run(lambda conn: ProfileStore(conn).merge_data(GAME, {PROFILE_KEY: [GOAL]}))
    assert await planned_progress_question(database, GAME) is None
    database.close()
