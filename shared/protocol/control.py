"""Messages between the brain and the Control Center window, on the /control socket.

Additive to messages.py: the overlay's /ws contract is unchanged. Fact values, notes and question
text can come from wiki or OCR text, so the Control Center shows them as plain text only.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from shared.protocol.messages import (
    MemoryToast,
    SettingsState,
    SettingsUpdate,
    VoiceOption,
)


# --- Read-only views of memory ---
class FactView(BaseModel):
    id: int
    subject: str
    attribute: str
    value: str
    source: Literal["player", "observed", "wiki"]
    confidence: float
    tentative: bool
    # Unix seconds. valid_to is None while the fact is current; old facts are closed, not deleted.
    valid_from: float
    valid_to: float | None = None


class QuestionView(BaseModel):
    id: int
    text: str
    options: list[str] = Field(default_factory=list)
    status: Literal["open", "answered", "dropped"]
    answer: str | None = None


class NoteView(BaseModel):
    id: int
    kind: Literal["rolling", "recap"]
    body: str  # Markdown source. Shown as plain text, never rendered.
    created_at: float


# --- Control Center to brain ---
class ControlHello(BaseModel):
    type: Literal["control.hello"] = "control.hello"
    protocol_version: int


class MemoryQuery(BaseModel):
    """Empty text lists the newest facts instead of searching."""

    type: Literal["memory.query"] = "memory.query"
    request_id: str
    text: str = Field(default="", max_length=500)
    # Also return facts whose validity window has closed, and settled questions.
    include_history: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class ContextPreview(BaseModel):
    """Asks for the exact context the talker would get for this query."""

    type: Literal["memory.context_preview"] = "memory.context_preview"
    request_id: str
    text: str = Field(max_length=500)


class VoicePreview(BaseModel):
    """Speak this sample line in the current voice, if the partner isn't already talking."""

    type: Literal["voice.preview"] = "voice.preview"
    text: str = Field(min_length=1, max_length=200)


class ControlShutdown(BaseModel):
    """Stop the brain cleanly, so the session is closed and its note written."""

    type: Literal["control.shutdown"] = "control.shutdown"


# --- Brain to Control Center ---
class MemoryResults(BaseModel):
    type: Literal["memory.results"] = "memory.results"
    request_id: str
    facts: list[FactView]
    questions: list[QuestionView]
    notes: list[NoteView]
    elapsed_ms: float


class MemoryContext(BaseModel):
    type: Literal["memory.context"] = "memory.context"
    request_id: str
    context: str
    elapsed_ms: float


class BrainStatus(BaseModel):
    """Which parts of the partner are running, so the Control Center can show what's on."""

    type: Literal["brain.status"] = "brain.status"
    mode: Literal["live", "replay"]
    game_title: str
    session_id: int | None = None
    watching: bool  # Screen reports (needs ANTHROPIC_API_KEY)
    listening: bool  # Speech to text (needs DEEPGRAM_API_KEY)
    speaking: bool  # Text to speech (needs the ElevenLabs key and a voice)
    talking: bool  # Replies from the talker model (needs GEMINI_API_KEY)
    tools: bool  # Player-turn tools: look closer, point, wiki
    wiki_url: str | None = None


class ControlError(BaseModel):
    type: Literal["control.error"] = "control.error"
    request_id: str | None = None
    message: str


class BrainDescription(BaseModel):
    """Printed by `python -m brain --describe`, before anything starts. Never holds key values."""

    protocol_version: int
    personalities: list[str]
    voices: list[VoiceOption]
    # Environment variable name -> whether .env or the environment sets it.
    keys_set: dict[str, bool]
    game_title: str
    game_process: str


ControlRequest = Annotated[
    ControlHello | MemoryQuery | ContextPreview | SettingsUpdate | VoicePreview | ControlShutdown,
    Field(discriminator="type"),
]
ControlReply = Annotated[
    MemoryResults | MemoryContext | BrainStatus | SettingsState | MemoryToast | ControlError,
    Field(discriminator="type"),
]

ControlRequestAdapter: TypeAdapter[ControlRequest] = TypeAdapter(ControlRequest)
ControlReplyAdapter: TypeAdapter[ControlReply] = TypeAdapter(ControlReply)
