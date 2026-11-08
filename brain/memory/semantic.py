"""The async side of meaning-based recall. It loads the embedding model when the player turns the
setting on, keeps the vector index in step with memory, and embeds each question off the loop.

Every failure leaves recall on keywords, which is how it worked before this existed.
"""

import asyncio
import contextlib
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar, cast, get_args

from brain.events import EventBus, FactLearned, SettingsChanged
from brain.memory import vectors
from brain.memory.db import Database
from brain.memory.embeddings import Embedder
from brain.memory.models import RecallMode
from brain.memory.recall import VectorQuery

log = logging.getLogger(__name__)

T = TypeVar("T")

_MODES = frozenset(get_args(RecallMode))
# Small, because a question asked mid-sync waits behind one batch on the embedding thread.
_BATCH = 8
# Repeated queries, such as the director's tip query, skip the model.
_CACHE_SIZE = 32
SLOW_EMBED_MS = 40.0


class SemanticRecall:
    def __init__(
        self,
        database: Database,
        bus: EventBus,
        load: Callable[[], Embedder],
        *,
        min_similarity: float,
        sync_interval_s: float = 15.0,
    ) -> None:
        """`load` builds the embedder. It's slow and may download, so it runs on a worker."""
        self._database = database
        self._events = bus.subscribe()
        self._load = load
        self._min_similarity = min_similarity
        self._sync_interval_s = sync_interval_s
        # Its own thread, so embedding never holds up the database worker.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-embed")
        self._mode: RecallMode = "keyword"
        self._embedder: Embedder | None = None
        self._load_failed = False
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    @property
    def mode(self) -> RecallMode:
        return self._mode

    @property
    def ready(self) -> bool:
        return self._embedder is not None

    def follow(self, settings: object) -> None:
        """Takes `memory_search` from the player's settings. Turning it on wakes `run()`, which
        loads the model in the background; until then, recall stays on keywords."""
        mode = getattr(settings, "memory_search", None)
        if mode not in _MODES or mode == self._mode:
            return
        log.info("Memory search: %s", mode)
        self._mode = cast(RecallMode, mode)
        # Picking it again is how the player retries after the model failed to load.
        self._load_failed = False
        self._wake.set()

    async def query(self, text: str | None) -> VectorQuery | None:
        """None means recall by keywords: the setting is off, the model isn't ready yet, or
        embedding failed."""
        embedder = self._embedder
        if self._mode == "keyword" or embedder is None or not text or not text.strip():
            return None
        vector = self._cache.get(text)
        if vector is None:
            started = time.perf_counter()
            try:
                vector = await self._run(embedder.embed_query, text)
            except Exception:
                log.exception("Couldn't embed the question; recalling by keywords")
                return None
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms > SLOW_EMBED_MS:
                log.warning("Embedding the question took %.1f ms", elapsed_ms)
            self._cache[text] = vector
            if len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(text)
        return VectorQuery(vector, self._mode == "semantic", self._min_similarity)

    async def refresh(self) -> int:
        """Loads the model if needed, then embeds whatever memory added since the last time.
        Returns how many facts and note chunks it embedded."""
        if self._mode == "keyword":
            return 0
        async with self._lock:
            if self._embedder is None and not await self._start():
                return 0
            return await self._sync()

    async def run(self) -> None:
        consume = asyncio.create_task(self._consume(), name="Memory search settings")
        try:
            while True:
                try:
                    await self.refresh()
                except Exception:
                    log.exception("Couldn't update the memory vector index")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._sync_interval_s)
                self._wake.clear()
        finally:
            consume.cancel()
            self._executor.shutdown(wait=False, cancel_futures=True)

    async def _start(self) -> bool:
        if self._load_failed:
            return False
        try:
            embedder = await self._run(self._load)
            await self._database.run(
                lambda conn: vectors.prepare(conn, embedder.model, embedder.dims)
            )
        except Exception:
            self._load_failed = True
            log.exception(
                "Meaning-based memory search couldn't start, so recall uses keywords."
                " Pick it again in settings to retry"
            )
            return False
        self._embedder = embedder
        return True

    async def _sync(self) -> int:
        embedder = self._embedder
        if embedder is None:
            return 0
        done = 0
        while items := await self._database.run(partial(vectors.pending, max_items=_BATCH)):
            found = await self._run(embedder.embed_passages, [item.text for item in items])
            await self._database.run(partial(vectors.store, items=items, vectors=found))
            done += len(items)
        if done:
            log.info("Embedded %d memory items for meaning-based recall", done)
        return done

    async def _consume(self) -> None:
        while True:
            event = await self._events.get()
            if isinstance(event, SettingsChanged):
                self.follow(event.settings)
            elif isinstance(event, FactLearned):
                # So a fact the player just told us can be found by meaning straight away.
                self._wake.set()

    async def _run(self, fn: Callable[..., T], *args: object) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)
