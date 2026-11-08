"""Offline memory administration over the dashboard's private subprocess pipe."""

from typing import Literal

from pydantic import BaseModel, Field

from shared.protocol.control import FactView


class MemoryAdminRequest(BaseModel):
    operation: Literal["list", "remember", "forget", "clear"] = "list"
    fact_id: int | None = Field(default=None, ge=1)
    game: str | None = Field(default=None, max_length=200)
    subject: str = Field(default="", max_length=200)
    attribute: str = Field(default="", max_length=200)
    value: str = Field(default="", max_length=2000)
    confirmation: str = ""


class AdminFact(FactView):
    game: str | None


class MemoryAdminResult(BaseModel):
    facts: list[AdminFact]
    total_facts: int
    notes: int
    events: int
    questions: int
    database: str
    backup: str | None = None
