"""Facts about the player and this playthrough, and the questions that settle them.

`remember` is the only write path, so the trust rules can't be bypassed: player > observed > wiki,
old facts are closed rather than overwritten, and disagreement between trusted sources goes to the
player. See docs/DECISIONS.md for why enemy stats don't belong here.
"""

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterable
from typing import get_args

from brain.memory.fact_records import (
    YES_NO,
    NewFact,
    clean,
    conflict_text,
    is_yes_no,
    possessive,
    same_value,
    to_fact,
    to_question,
)
from brain.memory.fts import to_match_query
from brain.memory.models import Fact, Question, RememberResult, Source

log = logging.getLogger(__name__)

LOW_CONFIDENCE = 0.5
CONFIRM_BOOST = 0.1
# Only the player's own statements and the screen can settle a fact. A wiki can't.
TRUSTED: frozenset[str] = frozenset({"player", "observed"})
_AUTHORITY_ORDER = "CASE source WHEN 'player' THEN 0 WHEN 'observed' THEN 1 ELSE 2 END"


class FactStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    def remember(
        self,
        game: str | None,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        session_id: int | None = None,
    ) -> RememberResult:
        subject, attribute = clean(subject, "subject"), clean(attribute, "attribute")
        value = clean(value, "value")
        if source not in get_args(Source):
            raise ValueError(f"Unknown fact source: {source!r}")
        # Written this way round so NaN is rejected too.
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1: {confidence!r}")

        new = NewFact(game, session_id, subject, attribute, value, source, confidence)
        with self._conn:
            current = self._current_exact(game, subject, attribute)
            match = next((f for f in current if same_value(f.value, value)), None)
            if match is not None:
                return self._confirm(match, source, confidence)
            if not current:
                return self._store_first(new)
            return self._resolve_difference(new, current)

    def current(
        self,
        game: str | None,
        subject: str | None = None,
        attribute: str | None = None,
        limit: int = 50,
    ) -> list[Fact]:
        subject = " ".join(subject.split()) if subject is not None else None
        attribute = " ".join(attribute.split()) if attribute is not None else None
        sql = (
            "SELECT * FROM facts WHERE valid_to IS NULL AND (game = ? OR game IS NULL)"
            " AND (? IS NULL OR subject = ?) AND (? IS NULL OR attribute = ?)"
            f" ORDER BY {_AUTHORITY_ORDER}, valid_from DESC, id DESC LIMIT ?"
        )
        params = (game, subject, subject, attribute, attribute, limit)
        return [to_fact(row) for row in self._rows(sql, *params)]

    def search(self, game: str | None, query: str, limit: int = 10) -> list[Fact]:
        match = to_match_query(query)
        if match is None:
            return []
        sql = (
            "SELECT f.* FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid"
            " WHERE facts_fts MATCH ? AND f.valid_to IS NULL AND (f.game = ? OR f.game IS NULL)"
            " ORDER BY rank LIMIT ?"
        )
        return [to_fact(row) for row in self._rows(sql, match, game, limit)]

    def close(self, fact_id: int) -> None:
        with self._conn:
            self._close([fact_id])

    def next_question(self, game: str | None) -> Question | None:
        rows = self._rows(
            "SELECT * FROM questions WHERE status = 'open' AND asked_at IS NULL"
            " AND (game = ? OR game IS NULL) ORDER BY created_at, id",
            game,
        )
        for question in map(to_question, rows):
            linked = self._facts_by_id(question.fact_ids)
            if not question.fact_ids or any(fact.valid_to is None for fact in linked):
                return question
            # Newer information already settled it, so asking would only be nagging. Dropping here
            # rather than in close() keeps a question the player is answering answerable.
            log.info("Dropping question %s: its facts are no longer current", question.id)
            self.drop_question(question.id)
        return None

    def mark_asked(self, question_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE questions SET asked_at = ? WHERE id = ? AND status = 'open'"
                " AND asked_at IS NULL",
                (self._clock(), question_id),
            )

    def drop_question(self, question_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE questions SET status = 'dropped' WHERE id = ? AND status = 'open'",
                (question_id,),
            )

    def answer_question(self, question_id: int, answer: str) -> RememberResult | None:
        rows = self._rows("SELECT * FROM questions WHERE id = ?", question_id)
        if not rows or rows[0]["status"] != "open":
            log.warning("Ignoring answer to unknown or closed question %s", question_id)
            return None
        answer = " ".join(answer.split())
        if not answer:
            log.warning("Ignoring empty answer to question %s", question_id)
            return None

        question = to_question(rows[0])
        with self._conn:
            linked = self._facts_by_id(question.fact_ids)
            if is_yes_no(question) and answer.casefold() in ("yes", "no"):
                result = self._apply_yes_no(answer.casefold() == "yes", linked)
            else:
                result = self._apply_free_text(answer, rows[0]["session_id"], question, linked)
            self._conn.execute(
                "UPDATE questions SET status = 'answered', answer = ?, answered_at = ?"
                " WHERE id = ?",
                (answer, self._clock(), question_id),
            )
        return result

    def _confirm(self, fact: Fact, source: Source, confidence: float) -> RememberResult:
        confidence = min(1.0, max(fact.confidence, confidence) + CONFIRM_BOOST)
        tentative = fact.tentative and source not in TRUSTED
        self._conn.execute(
            "UPDATE facts SET confidence = ?, tentative = ? WHERE id = ?",
            (confidence, tentative, fact.id),
        )
        if not tentative:
            # The trusted source just answered it, so asking the player too would be nagging.
            for question in self._open_questions(fact.game):
                if is_yes_no(question) and question.fact_ids == [fact.id]:
                    self.drop_question(question.id)
        return RememberResult("confirmed", fact=self._fact(fact.id))

    def _store_first(self, new: NewFact) -> RememberResult:
        unsure = new.source in TRUSTED and new.confidence < LOW_CONFIDENCE
        fact = self._insert(new, tentative=unsure or new.source == "wiki")
        if not unsure:
            return RememberResult("stored", fact=fact)
        text = f"Is {possessive(new.subject, new.attribute)} {new.value}?"
        question = self._open_question(new, text, YES_NO, [fact.id])
        return RememberResult("uncertain", fact=fact, question=question)

    def _resolve_difference(self, new: NewFact, current: list[Fact]) -> RememberResult:
        sources = {fact.source for fact in current}
        # A shaky reading mustn't close something we're surer of: low confidence means ask.
        if new.source in TRUSTED and new.confidence < LOW_CONFIDENCE:
            return self._record_conflict(new, current)
        if new.source == "wiki":
            if sources & TRUSTED:
                return RememberResult("ignored", fact=current[0])
        elif (TRUSTED - {new.source}) & sources:
            return self._record_conflict(new, current)

        # What's left is a higher authority replacing the wiki, or a source correcting itself.
        closed = self._close(fact.id for fact in current)
        fact = self._insert(new, tentative=new.source == "wiki")
        return RememberResult("replaced", fact=fact, closed=closed)

    def _record_conflict(self, new: NewFact, current: list[Fact]) -> RememberResult:
        fact = self._insert(new, tentative=True)
        involved = [*current, fact]
        ids = [item.id for item in involved]
        options = list(dict.fromkeys(item.value for item in involved))
        text = conflict_text(new.subject, new.attribute, options)

        questions = self._open_questions(new.game)
        existing = next((q for q in questions if set(q.fact_ids) & set(ids)), None)
        if existing is None:
            question = self._open_question(new, text, options, ids)
            return RememberResult("conflict", fact=fact, question=question)

        # One question per disputed fact, so more readings don't turn into more interruptions.
        merged = list(dict.fromkeys([*existing.fact_ids, *ids]))
        self._conn.execute(
            "UPDATE questions SET text = ?, options = ?, fact_ids = ? WHERE id = ?",
            (text, json.dumps(options), json.dumps(merged), existing.id),
        )
        return RememberResult("conflict", fact=fact, question=self._question(existing.id))

    def _apply_yes_no(self, confirmed: bool, linked: list[Fact]) -> RememberResult:
        fact = next((item for item in linked if item.valid_to is None), None)
        if fact is None:
            # Something newer already closed it. The answer no longer applies to anything.
            return RememberResult("ignored" if confirmed else "replaced")
        if not confirmed:
            return RememberResult("replaced", closed=self._close([fact.id]))
        self._conn.execute(
            "UPDATE facts SET tentative = 0, confidence = 1.0 WHERE id = ?", (fact.id,)
        )
        return RememberResult("confirmed", fact=self._fact(fact.id))

    def _apply_free_text(
        self, answer: str, session_id: int | None, question: Question, linked: list[Fact]
    ) -> RememberResult:
        subject = linked[0].subject if linked else question.subject
        attribute = linked[0].attribute if linked else question.attribute
        if not subject or not attribute:
            log.warning("Question %s has nothing to file its answer under", question.id)
            return RememberResult("ignored")
        # Includes newer unlinked facts, because the player's answer must end up as the only
        # current value for this subject and attribute.
        rivals = self._current_exact(question.game, subject, attribute)
        closed = self._close(item.id for item in [*linked, *rivals] if item.valid_to is None)
        new = NewFact(question.game, session_id, subject, attribute, answer, "player", 1.0)
        return RememberResult("replaced", fact=self._insert(new, tentative=False), closed=closed)

    def _insert(self, new: NewFact, tentative: bool) -> Fact:
        cursor = self._conn.execute(
            "INSERT INTO facts (game, session_id, subject, attribute, value, source, confidence,"
            " tentative, valid_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*new, tentative, self._clock()),
        )
        return self._fact(int(cursor.lastrowid or 0))

    def _close(self, fact_ids: Iterable[int]) -> list[Fact]:
        ids = list(dict.fromkeys(fact_ids))
        now = self._clock()
        self._conn.executemany(
            "UPDATE facts SET valid_to = ? WHERE id = ? AND valid_to IS NULL",
            [(now, fact_id) for fact_id in ids],
        )
        return self._facts_by_id(ids)

    def _open_question(
        self, new: NewFact, text: str, options: list[str], fact_ids: list[int]
    ) -> Question:
        now = self._clock()
        cursor = self._conn.execute(
            "INSERT INTO questions (game, session_id, text, options, fact_ids, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (new.game, new.session_id, text, json.dumps(options), json.dumps(fact_ids), now),
        )
        return self._question(int(cursor.lastrowid or 0))

    def _rows(self, sql: str, *params: object) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def _question(self, question_id: int) -> Question:
        return to_question(self._rows("SELECT * FROM questions WHERE id = ?", question_id)[0])

    def _open_questions(self, game: str | None) -> list[Question]:
        sql = "SELECT * FROM questions WHERE status = 'open' AND game IS ? ORDER BY id"
        return [to_question(row) for row in self._rows(sql, game)]

    def _fact(self, fact_id: int) -> Fact:
        return to_fact(self._rows("SELECT * FROM facts WHERE id = ?", fact_id)[0])

    def _facts_by_id(self, fact_ids: list[int]) -> list[Fact]:
        """Includes closed facts, and keeps the given order so "first linked fact" is stable."""
        rows = [self._rows("SELECT * FROM facts WHERE id = ?", fact_id) for fact_id in fact_ids]
        return [to_fact(found[0]) for found in rows if found]

    def _current_exact(self, game: str | None, subject: str, attribute: str) -> list[Fact]:
        """Unlike current(), a NULL game only matches NULL, so games never settle each other."""
        sql = (
            "SELECT * FROM facts WHERE valid_to IS NULL AND game IS ? AND subject = ?"
            f" AND attribute = ? ORDER BY {_AUTHORITY_ORDER}, valid_from DESC, id DESC"
        )
        return [to_fact(row) for row in self._rows(sql, game, subject, attribute)]
