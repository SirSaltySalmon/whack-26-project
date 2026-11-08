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
    # How much the ElevenLabs voice varies its delivery. "classic" is the original flat sound,
    # kept so the two can be compared by ear.
    voice_style: Literal["expressive", "classic"] = "expressive"


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
    # The box being pointed at, so the pointer can sit beside it instead of covering it.
    target: Rect | None = None
    # Lifetime in milliseconds. Keep it short for world targets: the world may scroll away.
    ttl_ms: int | None = None


class PointerHide(BaseModel):
    type: Literal["pointer.hide"] = "pointer.hide"


class CardShow(BaseModel):
    """Body is sanitized plain text, never raw HTML.

    Set page_url to show the real site in the sandboxed wiki window, with body as the text shown if
    it can't load. Send it only for lookups the player asked for, so the page can't change while
    they're reading. The overlay has one wiki window, so a new page_url reuses it.
    """

    type: Literal["card.show"] = "card.show"
    card_id: str
    title: str
    body: str
    source_url: str | None = None
    page_url: str | None = None


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


class VoiceOption(BaseModel):
    name: str
    id: str


class SettingsState(BaseModel):
    type: Literal["settings.state"] = "settings.state"
    settings: Settings
    # What the settings panel can offer.
    personalities: list[str] = Field(default_factory=list)
    voices: list[VoiceOption] = Field(default_factory=list)


class PageRead(BaseModel):
    """Asks for the wiki window's rendered text. The brain sends it only for its own wiki's host."""

    type: Literal["page.read"] = "page.read"
    request_id: str


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


class CardNavigated(BaseModel):
    """The wiki window's page changed. The URL and title come from a website: treat them as data."""

    type: Literal["card.navigated"] = "card.navigated"
    card_id: str
    url: str
    title: str | None = None


class QuestionAnswer(BaseModel):
    type: Literal["question.answer"] = "question.answer"
    question_id: str
    answer: str


class SettingsUpdate(BaseModel):
    type: Literal["settings.update"] = "settings.update"
    settings: Settings


class PageContent(BaseModel):
    """The wiki window's rendered text, in reply to page.read. Every field comes from a website, so
    treat all of it as untrusted data."""

    type: Literal["page.content"] = "page.content"
    request_id: str
    card_id: str
    url: str  # From WebContents.getURL() at read time
    title: str | None = None
    text: str = Field(max_length=200_000)
    visible_text: str = Field(max_length=4_000)
    truncated: bool = False


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
    | SettingsState
    | PageRead,
    Field(discriminator="type"),
]
OverlayMessage = Annotated[
    OverlayReady
    | OverlayRects
    | CardClosed
    | CardNavigated
    | QuestionAnswer
    | SettingsUpdate
    | PageContent,
    Field(discriminator="type"),
]

BrainMessageAdapter: TypeAdapter[BrainMessage] = TypeAdapter(BrainMessage)
OverlayMessageAdapter: TypeAdapter[OverlayMessage] = TypeAdapter(OverlayMessage)

# The Control Center's messages are in control.py, and Protocol, which lists every direction for
# the generated TypeScript, is in __init__.py.
