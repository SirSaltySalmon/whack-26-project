"""Offline memory administration over the dashboard's private subprocess pipe."""

from typing import Literal

from pydantic import BaseModel, Field

from shared.protocol.control import FactView, NoteView


class MemoryAdminRequest(BaseModel):
    operation: Literal[
        "list", "remember", "forget", "clear", "edit_note", "delete_note", "seed"
    ] = "list"
    fact_id: int | None = Field(default=None, ge=1)
    note_id: int | None = Field(default=None, ge=1)
    body: str = Field(default="", max_length=20000)
    expected_body: str | None = Field(default=None, max_length=20000)
    game: str | None = Field(default=None, max_length=200)
    subject: str = Field(default="", max_length=200)
    attribute: str = Field(default="", max_length=200)
    value: str = Field(default="", max_length=2000)
    confirmation: str = ""


class AdminFact(FactView):
    game: str | None


class AdminNote(NoteView):
    session_id: int
    game: str


class MemoryAdminResult(BaseModel):
    facts: list[AdminFact]
    note_items: list[AdminNote] = Field(default_factory=list)
    total_facts: int
    notes: int
    events: int
    questions: int
    database: str
    backup: str | None = None
