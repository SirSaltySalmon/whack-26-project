"""Builds what a reply knows, for MemoryService. Kept apart because service.py is at its length
limit. Runs on the voice path: database reads in memory's own thread, embedding in a worker."""

import logging
import time
from collections.abc import Callable, Mapping

from brain.memory.db import Database
from brain.memory.gather import gather_context, last_partner_line, recall_text
from brain.memory.layers import TalkerContext, build_context
from brain.memory.semantic import SemanticRecall

log = logging.getLogger(__name__)

SLOW_CONTEXT_MS = 50.0


class ContextAssembler:
    def __init__(
        self,
        database: Database,
        game: str,
        semantic: SemanticRecall | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._database = database
        self._game = game
        self._semantic = semantic
        # The same wall clock the events table is stamped with, for TIME.
        self._clock = clock

    async def build(
        self,
        session_id: int,
        asked: int | None,
        live_state: Mapping[str, str],
        query: str | None,
        current: str | None,
    ) -> TalkerContext:
        started = time.perf_counter()
        vector = None
        semantic = self._semantic
        if semantic is not None and semantic.mode != "keyword" and semantic.ready and query:
            # Meaning-based recall searches the same text keyword recall does: the query plus
            # the partner's last line, so "that" finds what the partner was talking about.
            said = await self._database.run(lambda conn: last_partner_line(conn, session_id))
            vector = await semantic.query(recall_text(query, said))
        now = self._clock()
        context = await self._database.run(
            lambda conn: build_context(
                gather_context(
                    conn,
                    self._game,
                    session_id,
                    live_state,
                    query,
                    asked_id=asked,
                    vector=vector,
                    current=current,
                    now=now,
                )
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > SLOW_CONTEXT_MS:
            log.warning("Memory context took %.1f ms", elapsed_ms)
        return context
