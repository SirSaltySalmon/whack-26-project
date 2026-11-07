"""Source of truth for brain <-> overlay messages.

TypeScript types are generated from these models, so run `npm --prefix overlay run gen:protocol`
after any change. All on-screen coordinates in this file are Electron DIPs.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

PROTOCOL_VERSION = 1


class Rect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ElementRect(BaseModel):
    element_id: str
    rect: Rect


class Settings(BaseModel):
    proactive: bool = True
    personality: str = "supportive"
    voice_id: str | None = None


# --- Brain to overlay ---
class SubtitleChunk(BaseModel):
    type: Literal["subtitle.chunk"] = "subtitle.chunk"
    utterance_id: str
    text: str
    final: bool = False


class AvatarState(BaseModel):
    type: Literal["avatar.state"] = "avatar.state"
    state: Literal["idle", "listening", "talking", "reacting"]


class PointerFly(BaseModel):
    type: Literal["pointer.fly"] = "pointer.fly"
    x: float
    y: float
    label: str | None = None


class PointerHide(BaseModel):
    type: Literal["pointer.hide"] = "pointer.hide"


class CardShow(BaseModel):
    """Body is sanitized plain text. Never put live web pages or raw HTML here."""

    type: Literal["card.show"] = "card.show"
    card_id: str
    title: str
    body: str
    source_url: str | None = None


class CardUpdate(BaseModel):
    type: Literal["card.update"] = "card.update"
    card_id: str
    title: str | None = None
    body: str | None = None


class CardClose(BaseModel):
    type: Literal["card.close"] = "card.close"
    card_id: str


class MemoryToast(BaseModel):
    type: Literal["toast.memory"] = "toast.memory"
    text: str
    source: Literal["player", "observed", "wiki"]


class QuestionAsk(BaseModel):
    type: Literal["question.ask"] = "question.ask"
    question_id: str
    text: str
    options: list[str] = Field(default_factory=list)


class SettingsState(BaseModel):
    type: Literal["settings.state"] = "settings.state"
    settings: Settings


# --- Overlay to brain ---
class OverlayReady(BaseModel):
    type: Literal["overlay.ready"] = "overlay.ready"
    protocol_version: int
    display_scale: float
    width: float
    height: float


class OverlayRects(BaseModel):
    """Every visible element. The brain masks these so the AI can't read its own UI."""

    type: Literal["overlay.rects"] = "overlay.rects"
    rects: list[ElementRect]


class CardClosed(BaseModel):
    type: Literal["card.closed"] = "card.closed"
    card_id: str


class QuestionAnswer(BaseModel):
    type: Literal["question.answer"] = "question.answer"
    question_id: str
    answer: str


class SettingsUpdate(BaseModel):
    type: Literal["settings.update"] = "settings.update"
    settings: Settings


BrainMessage = Annotated[
    SubtitleChunk
    | AvatarState
    | PointerFly
    | PointerHide
    | CardShow
    | CardUpdate
    | CardClose
    | MemoryToast
    | QuestionAsk
    | SettingsState,
    Field(discriminator="type"),
]
OverlayMessage = Annotated[
    OverlayReady | OverlayRects | CardClosed | QuestionAnswer | SettingsUpdate,
    Field(discriminator="type"),
]

BrainMessageAdapter: TypeAdapter[BrainMessage] = TypeAdapter(BrainMessage)
OverlayMessageAdapter: TypeAdapter[OverlayMessage] = TypeAdapter(OverlayMessage)


class Protocol(BaseModel):
    """Exists only so one JSON Schema document can describe both directions."""

    brain: BrainMessage
    overlay: OverlayMessage
