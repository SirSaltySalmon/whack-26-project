"""SemanticRecall: the memory_search setting, loading in the background, and falling back to
keywords whenever meaning-based search can't run."""

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable

import pytest

from brain.events import EventBus, FactLearned, SettingsChanged
from brain.llm.base import LLMUnavailableError, TextLLM
from brain.memory import vectors
from brain.memory.context import ContextLimits
from brain.memory.db import Database, connect
from brain.memory.embeddings import Embedder
from brain.memory.notes import NoteWriter
from brain.memory.semantic import SemanticRecall
from brain.memory.service import MemoryService
from brain.tests.fake_embedder import FakeEmbedder
from shared.protocol.messages import Settings

GAME = "Test Game"


def no_llm() -> TextLLM:
    raise LLMUnavailableError("no key in tests")


class Rig:
    def __init__(self, embedder: FakeEmbedder) -> None:
        conn = connect(":memory:")
        try:
            vectors.load_extension(conn)
        except (AttributeError, sqlite3.Error) as error:
            pytest.skip(f"sqlite-vec can't load here: {error}")
        self.database = Database(conn)
        self.bus = EventBus()
        self.embedder = embedder
        self.loads = 0
        self.load_fails = False
        self.semantic = SemanticRecall(
            self.database, self.bus, self._load, min_similarity=0.1, sync_interval_s=60
        )
        self.memory = MemoryService(
            self.database, self.bus, self._send, GAME, NoteWriter(no_llm), semantic=self.semantic
        )

    def _load(self) -> Embedder:
        self.loads += 1
        if self.load_fails:
            raise RuntimeError("no model in tests")
        return self.embedder

    async def _send(self, message: object) -> None:
        pass


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    made = Rig(FakeEmbedder({"house": "base"}))
    await made.memory.start()
    yield made
    made.database.close()


async def wait_until(check: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        # Polling, because the state changes on SemanticRecall's worker thread with no event.
        while not check():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def test_settings_default_to_keywords_and_old_payloads_still_load() -> None:
    assert Settings().memory_search == "keyword"
    assert Settings.model_validate({"proactive": False}).memory_search == "keyword"


async def test_keyword_mode_never_loads_the_model(rig: Rig) -> None:
    rig.semantic.follow(Settings())
    assert await rig.semantic.refresh() == 0
    assert await rig.semantic.query("where's my house") is None
    assert rig.loads == 0


async def test_turning_it_on_loads_indexes_and_embeds_queries(rig: Rig) -> None:
    await rig.memory.remember("base", "location", "left of spawn", "player", 0.9)
    rig.semantic.follow(Settings(memory_search="hybrid"))
    assert await rig.semantic.query("anything") is None  # Not loaded yet: keywords meanwhile.
    assert await rig.semantic.refresh() == 1
    hybrid = await rig.semantic.query("where's my house")
    assert hybrid is not None and not hybrid.semantic_only
    rig.semantic.follow(Settings(memory_search="semantic"))
    semantic = await rig.semantic.query("where's my house")
    assert semantic is not None and semantic.semantic_only
    assert rig.loads == 1
    assert rig.embedder.queries == ["where's my house"]  # The second ask came from the cache.


async def test_context_recalls_by_meaning_once_switched_on(rig: Rig) -> None:
    await rig.memory.remember("base", "location", "left of spawn", "player", 0.9)
    # Enough newer facts to push it out of PLAYER, so only recall can bring it back.
    for i in range(ContextLimits().max_player_facts):
        await rig.memory.remember("filler", f"slot {i}", f"value {i}", "player", 0.9)
    before = await rig.memory.context({}, "where's my house")
    rig.semantic.follow(Settings(memory_search="semantic"))
    await rig.semantic.refresh()
    after = await rig.memory.context({}, "where's my house")
    assert "RECALL" not in before
    assert "RECALL: base / location: left of spawn" in after


async def test_a_failed_load_stays_on_keywords_until_picked_again(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.load_fails = True
    rig.semantic.follow(Settings(memory_search="hybrid"))
    with caplog.at_level(logging.ERROR):
        assert await rig.semantic.refresh() == 0
    assert "couldn't start" in caplog.text
    assert await rig.semantic.query("where's my house") is None
    # The loop refreshes every few seconds, so it mustn't retry a failed load each time.
    rig.load_fails = False
    await rig.semantic.refresh()
    assert not rig.semantic.ready and rig.loads == 1
    rig.semantic.follow(Settings())
    rig.semantic.follow(Settings(memory_search="hybrid"))
    await rig.semantic.refresh()
    assert rig.semantic.ready


async def test_a_failed_query_falls_back_to_keywords(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.semantic.follow(Settings(memory_search="hybrid"))
    await rig.semantic.refresh()
    rig.embedder.fail = True
    with caplog.at_level(logging.ERROR):
        assert await rig.semantic.query("where's my house") is None
    assert "Couldn't embed the question" in caplog.text


async def test_run_follows_settings_and_new_facts_from_the_bus(rig: Rig) -> None:
    task = asyncio.create_task(rig.semantic.run())
    try:
        rig.bus.publish(SettingsChanged(settings=Settings(memory_search="hybrid")))
        await wait_until(lambda: rig.semantic.ready)
        await rig.memory.remember("base", "location", "left of spawn", "player", 0.9)
        rig.bus.publish(
            FactLearned(subject="base", attribute="location", source="player", outcome="stored")
        )
        await wait_until(lambda: "base location: left of spawn" in rig.embedder.passages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
