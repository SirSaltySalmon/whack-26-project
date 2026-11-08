"""Facts about the player and this playthrough, and the questions that settle them.

`remember` is the only write path for claims, so the trust rules can't be bypassed: player >
observed > wiki, and old facts are closed rather than overwritten. The player's word replaces a
guess outright; only the screen disputing the player is asked about. See docs/DECISIONS.md for why
enemy stats don't belong here.
"""

import json
import logging
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
from brain.memory.fact_table import AUTHORITY_ORDER, FactTable
from brain.memory.fts import to_match_query
from brain.memory.models import Fact, Question, RememberResult, Source
from brain.memory.rejections import is_rejected, update_rejected

log = logging.getLogger(__name__)

LOW_CONFIDENCE = 0.5
CONFIRM_BOOST = 0.1
# Only the player's own statements and the screen can settle a fact. A wiki can't.
TRUSTED: frozenset[str] = frozenset({"player", "observed"})


class FactStore(FactTable):
    def remember(
        self,
        game: str | None,
        subject: str,
        attribute: str,
        value: str,
        source: Source,
        confidence: float,
        session_id: int | None = None,
        *,
        tentative: bool = False,
    ) -> RememberResult:
        """`tentative` marks an inference, such as a guess from gear icons, rather than a reading.

        It's stored unconfirmed and opens no question, because its caller queues its own.
        """
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
            if source == "player":
                update_rejected(self._conn, game, subject, attribute, lift=value)
            elif is_rejected(self._conn, game, subject, attribute, value):
                log.info("Ignoring %s / %s = %r: the player said no", subject, attribute, value)
                return RememberResult("ignored", fact=current[0] if current else None)
            match = next((f for f in current if same_value(f.value, value)), None)
            if match is not None:
                return self._confirm(match, source, confidence, tentative)
            if not current:
                return self._store_first(new, tentative)
            return self._resolve_difference(new, current, tentative)

    def forget(self, game: str | None, subject: str, attribute: str) -> list[Fact]:
        """Closes every current value for this exact key and opens no question. Returns them."""
        subject, attribute = clean(subject, "subject"), clean(attribute, "attribute")
        with self._conn:
            closed = self._close(f.id for f in self._current_exact(game, subject, attribute))
            values = [fact.value for fact in closed]
            update_rejected(self._conn, game, subject, attribute, add=values)
            self._drop_settled(closed)
        return closed

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
            f" ORDER BY {AUTHORITY_ORDER}, valid_from DESC, id DESC LIMIT ?"
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

    def answer_question(
        self, question_id: int, answer: str, correction: str | None = None
    ) -> RememberResult | None:
        """`correction` is the right value after a "No". Questions dropped unanswered still count,
        because the player may come back to one."""
        rows = self._rows("SELECT * FROM questions WHERE id = ?", question_id)
        if not rows or rows[0]["status"] == "answered":
            log.warning("Ignoring answer to unknown or answered question %s", question_id)
            return None
        answer = " ".join(answer.split())
        correction = " ".join((correction or "").split()) or None
        if not answer:
            log.warning("Ignoring empty answer to question %s", question_id)
            return None

        question = to_question(rows[0])
        said = answer.casefold()
        with self._conn:
            linked = self._facts_by_id(question.fact_ids)
            if is_yes_no(question) and said in ("yes", "no") and not (said == "no" and correction):
                result = self._apply_yes_no(said == "yes", linked)
            else:
                value = correction or answer
                result = self._apply_free_text(value, rows[0]["session_id"], question, linked)
            self._conn.execute(
                "UPDATE questions SET status = 'answered', answer = ?, answered_at = ?"
                " WHERE id = ?",
                (answer, self._clock(), question_id),
            )
        return result

    # --- Trust rules ---
    def _confirm(
        self, fact: Fact, source: Source, confidence: float, inferred: bool
    ) -> RememberResult:
        confidence = min(1.0, max(fact.confidence, confidence) + CONFIRM_BOOST)
        tentative = fact.tentative and (source not in TRUSTED or inferred)
        self._conn.execute(
            "UPDATE facts SET confidence = ?, tentative = ? WHERE id = ?",
            (confidence, tentative, fact.id),
        )
        if not tentative:
            # The trusted source just answered it, so asking the player too would be nagging.
            for question in self._open_questions(fact.game):
                if is_yes_no(question) and question.fact_ids == [fact.id]:
                    self._drop(question.id)
        confirmed = self._fact(fact.id)
        if source in TRUSTED and not inferred:
            self._settle_unknowns(confirmed)
        return RememberResult("confirmed", fact=confirmed)

    def _store_first(self, new: NewFact, inferred: bool) -> RememberResult:
        if inferred:
            return RememberResult("stored", fact=self._insert(new, tentative=True))
        unsure = new.source in TRUSTED and new.confidence < LOW_CONFIDENCE
        fact = self._insert(new, tentative=unsure or new.source == "wiki")
        if not unsure:
            self._settle_unknowns(fact)
            return RememberResult("stored", fact=fact)
        text = f"Is {possessive(new.subject, new.attribute)} {new.value}?"
        question = self._open_question(new, text, YES_NO, [fact.id])
        return RememberResult("uncertain", fact=fact, question=question)

    def _resolve_difference(
        self, new: NewFact, current: list[Fact], inferred: bool
    ) -> RememberResult:
        sources = {fact.source for fact in current}
        if new.source == "wiki":
            if sources & TRUSTED:
                return RememberResult("ignored", fact=current[0])
            return self._replace(new, current, tentative=True)
        if inferred:
            # A guess never disputes the player, and a shaky one mustn't close a surer fact.
            shaky = new.confidence < LOW_CONFIDENCE and any(not f.tentative for f in current)
            if "player" in sources or shaky:
                return RememberResult("ignored", fact=current[0])
            return self._replace(new, current, tentative=True)
        # A shaky reading mustn't close something we're surer of: low confidence means ask.
        if new.confidence < LOW_CONFIDENCE:
            return self._record_conflict(new, current)
        if new.source == "observed" and "player" in sources:
            return self._record_conflict(new, current)
        # The player overruling a guess, a reading replacing the wiki, or a source fixing itself.
        return self._replace(new, current, tentative=False)

    def _replace(self, new: NewFact, current: list[Fact], tentative: bool) -> RememberResult:
        closed = self._close(fact.id for fact in current)
        if new.source == "player":
            self._reject_overruled(new.value, closed)
        fact = self._insert(new, tentative=tentative)
        self._drop_settled(closed)
        self._settle_unknowns(fact)
        return RememberResult("replaced", fact=fact, closed=closed)

    def _reject_overruled(self, value: str, closed: list[Fact]) -> None:
        # Only guesses: the player's own earlier claim may simply have changed since.
        wrong = [fact.value for fact in closed if fact.source != "player"]
        if wrong:
            first = closed[0]
            update_rejected(
                self._conn, first.game, first.subject, first.attribute, add=wrong, lift=value
            )

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
        if not confirmed:
            if linked:
                guess = linked[0]
                update_rejected(
                    self._conn, guess.game, guess.subject, guess.attribute, add=[guess.value]
                )
            closed = self._close([fact.id]) if fact is not None else []
            self._drop_settled(closed)
            return RememberResult("replaced", closed=closed)
        if fact is None:
            # Something newer already closed it. The answer no longer applies to anything.
            return RememberResult("ignored")
        self._conn.execute(
            "UPDATE facts SET tentative = 0, confidence = 1.0 WHERE id = ?", (fact.id,)
        )
        sure = self._fact(fact.id)
        self._settle_unknowns(sure)
        return RememberResult("confirmed", fact=sure)

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
        # Guesses the answer overruled were wrong, and so was any value a yes/no asked about.
        wrong = [item.value for item in closed if item.source != "player"]
        wrong += [item.value for item in linked] if is_yes_no(question) else []
        update_rejected(self._conn, question.game, subject, attribute, add=wrong, lift=answer)
        new = NewFact(question.game, session_id, subject, attribute, answer, "player", 1.0)
        fact = self._insert(new, tentative=False)
        self._drop_settled(closed)
        self._settle_unknowns(fact)
        return RememberResult("replaced", fact=fact, closed=closed)
