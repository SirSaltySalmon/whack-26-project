import asyncio
import json
from collections.abc import Awaitable, Callable

import pytest

from brain.learner.progress import (
    ATTRIBUTE,
    FALLBACK_QUESTION,
    SUBJECT,
    ProgressEstimate,
    ProgressScout,
)
from brain.llm.base import LLMUnavailableError
from brain.memory.models import Fact
from brain.perception.observation import Observation
from brain.tests.fakes import (
    FakeMemory,
    FakeOverlay,
    FakeVision,
    VisionReply,
    make_buffer,
    make_frame,
)

SURE = {
    "clues": ["Nights Edge", "Molten Armor"],
    "stage": "Pre-hardmode, Skeletron beaten.",
    "next_milestone": "Wall of Flesh",
    "confidence": 0.9,
}
UNCLEAR = {"clues": [], "stage": None, "next_milestone": None, "confidence": 0.1}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def seen(screen: str = "gameplay") -> Observation:
    return Observation(
        screen_type=screen,  # type: ignore[arg-type]
        summary="",
        player_action=None,
        health_visible=True,
        health_raw=None,
        health_percent=None,
        danger_level="none",
        threats=[],
        selected_item=None,
        menu_title=None,
        location=None,
        on_screen_text=[],
        notable=None,
        unsure=[],
    )


def scout(
    reply: VisionReply,
    memory: FakeMemory | None = None,
    clock: Clock | None = None,
    planned: Callable[[], Awaitable[str | None]] | None = None,
) -> tuple[ProgressScout, FakeVision, FakeMemory]:
    vision = FakeVision(reply)
    memory = memory or FakeMemory()
    found = ProgressScout(
        make_buffer(make_frame()),
        FakeOverlay(),
        vision,
        memory,
        "Some Game",
        max_edge_px=640,
        mask_padding_px=4,
        max_calls=2,
        retry_gap_s=60.0,
        recheck_s=600.0,
        planned_question=planned,
        clock=clock or Clock(),
    )
    return found, vision, memory


def known(source: str, confidence: float = 1.0, tentative: bool = False, at: float = 0.0) -> Fact:
    return Fact(1, None, SUBJECT, ATTRIBUTE, "Hardmode", source, confidence, tentative, at)  # type: ignore[arg-type]


def test_value_joins_stage_and_next_milestone() -> None:
    assert ProgressEstimate.model_validate(SURE).as_value() == (
        "Pre-hardmode, Skeletron beaten; next: Wall of Flesh"
    )
    assert ProgressEstimate.model_validate(UNCLEAR).as_value() is None


async def test_stores_a_guess_as_a_tentative_observed_fact_with_capped_confidence() -> None:
    found, vision, memory = scout(SURE)
    assert await found.check()
    assert memory.remembered == [
        (SUBJECT, ATTRIBUTE, "Pre-hardmode, Skeletron beaten; next: Wall of Flesh", "observed", 0.7)
    ]
    # Read off small icons, so the talker must hear it as unconfirmed.
    assert memory.tentative_remembered == [(SUBJECT, ATTRIBUTE)]
    call = vision.calls[0]
    assert call.detail == "high" and "Some Game" in call.prompt and "hotbar" in call.prompt


async def test_the_players_word_stops_the_scout_looking() -> None:
    memory = FakeMemory()
    memory.facts[(SUBJECT, ATTRIBUTE)] = known("player")
    found, vision, _ = scout(SURE, memory)
    assert not await found.check()
    assert vision.calls == []


async def test_a_sure_guess_holds_until_the_recheck_time() -> None:
    clock = Clock()
    memory = FakeMemory()
    memory.facts[(SUBJECT, ATTRIBUTE)] = known("observed", 0.7, at=clock.now)
    found, vision, _ = scout(SURE, memory, clock)
    assert not await found.check()
    clock.now += 600
    assert await found.check()


async def test_an_unclear_frame_stores_nothing_and_waits_before_retrying() -> None:
    clock = Clock()
    found, vision, memory = scout(UNCLEAR, clock=clock)
    assert await found.check()
    assert memory.remembered == []
    assert not await found.check()
    clock.now += 60
    assert await found.check()


async def test_an_open_inventory_earns_an_early_retry() -> None:
    found, vision, _ = scout(UNCLEAR)
    await found.check()
    found.notice(seen("inventory"), 0.0)
    assert await found.check()
    assert len(vision.calls) == 2


async def test_a_queued_question_is_only_revisited_from_the_inventory() -> None:
    memory = FakeMemory()
    memory.facts[(SUBJECT, ATTRIBUTE)] = known("observed", 0.3, tentative=True)
    found, _, _ = scout(SURE, memory)
    assert not await found.check()
    found.notice(seen("inventory"), 0.0)
    assert await found.check()


async def test_stops_after_its_call_budget() -> None:
    clock = Clock()
    found, vision, _ = scout(UNCLEAR, clock=clock)
    for _ in range(3):
        await found.check()
        clock.now += 60
    assert len(vision.calls) == 2


async def test_quota_refusal_gives_the_call_back() -> None:
    found, _, memory = scout(LLMUnavailableError("over quota"))
    assert not await found.check()
    assert found.calls == 0 and memory.remembered == []


async def test_menus_dont_wake_it_and_gameplay_does() -> None:
    found, vision, memory = scout(SURE)
    task = asyncio.create_task(found.run())
    found.notice(seen("menu"), 0.0)
    await asyncio.sleep(0.01)
    assert vision.calls == []
    # Inventory skips the throttle, so the test needn't wait it out.
    found.notice(seen("inventory"), 0.0)
    for _ in range(50):
        await asyncio.sleep(0.01)
        if memory.remembered:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(memory.remembered) == 1


ASKING = {**SURE, "progress_question": "Have you beaten Skeletron yet?"}
PLANNED = "Which boss did you beat last?"


def plan_says(text: str | None) -> Callable[[], Awaitable[str | None]]:
    async def planned() -> str | None:
        return text

    return planned


async def test_asks_only_where_the_player_is() -> None:
    # Other topics come from the game's planned questions, not from one frame.
    found, vision, memory = scout(ASKING)
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, "Have you beaten Skeletron yet?")]
    assert "questions:" not in vision.calls[0].prompt


async def test_the_planned_question_beats_one_drafted_from_a_frame() -> None:
    found, _, memory = scout(ASKING, planned=plan_says(PLANNED))
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, PLANNED)]


async def test_without_a_plan_yet_the_drafted_question_is_used() -> None:
    found, _, memory = scout(ASKING, planned=plan_says(None))
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, "Have you beaten Skeletron yet?")]


async def test_a_broken_plan_read_falls_back_to_the_drafted_question() -> None:
    async def broken() -> str | None:
        raise RuntimeError("database is locked")

    found, _, memory = scout(ASKING, planned=broken)
    assert await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, "Have you beaten Skeletron yet?")]


async def test_a_shaky_guess_is_asked_about_not_stored() -> None:
    found, _, memory = scout({**ASKING, "confidence": 0.3})
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, "Have you beaten Skeletron yet?")]
    assert memory.remembered == []


async def test_a_shaky_guess_isnt_stored_even_when_the_question_is_already_open() -> None:
    found, _, memory = scout({**ASKING, "confidence": 0.3}, FakeMemory(wonder_result=None))
    await found.check()
    assert memory.remembered == []


async def test_a_fair_tentative_guess_is_rechecked_after_the_recheck_time() -> None:
    # Every guess the scout stores is tentative, so that alone mustn't stop it ever looking again.
    clock = Clock()
    memory = FakeMemory()
    memory.facts[(SUBJECT, ATTRIBUTE)] = known("observed", 0.7, tentative=True, at=clock.now)
    found, _, _ = scout(SURE, memory, clock)
    assert not await found.check()
    clock.now += 600
    assert await found.check()


async def test_no_drafted_question_and_no_plan_falls_back_to_a_plain_one() -> None:
    found, _, memory = scout(UNCLEAR)
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, FALLBACK_QUESTION)]


async def test_over_quota_still_asks_the_player() -> None:
    found, _, memory = scout(LLMUnavailableError("over quota"))
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, FALLBACK_QUESTION)]


def test_the_reply_schema_is_one_gemini_accepts() -> None:
    # Gemini's response_schema rejects additionalProperties with a 400, so every call failed live.
    assert "additionalProperties" not in json.dumps(ProgressEstimate.model_json_schema())


async def test_over_quota_asks_the_planned_question_when_there_is_one() -> None:
    found, _, memory = scout(LLMUnavailableError("over quota"), planned=plan_says(PLANNED))
    await found.check()
    assert memory.wondered == [(SUBJECT, ATTRIBUTE, PLANNED)]
