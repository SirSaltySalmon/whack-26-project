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


class Pacing(BaseModel):
    """How often the partner may speak up unasked, in seconds. The director's rules apply it.

    A player setting rather than config, so it can be tuned while playing.
    """

    # Between two reactions to game events.
    event_gap_s: float = Field(default=8.0, ge=0)
    # Between two questions. The quiet stretch after anyone talks is off by default: a question
    # still never interrupts the partner, and is held while the player is mid-sentence.
    question_gap_s: float = Field(default=45.0, ge=0)
    question_quiet_s: float = Field(default=0.0, ge=0)
    # Tips, with hints on: the first after arriving, then one per gap. A 0 gap turns them off.
    advice_first_s: float = Field(default=45.0, ge=0)
    advice_gap_s: float = Field(default=90.0, ge=0)
    advice_quiet_s: float = Field(default=10.0, ge=0)


class Settings(BaseModel):
    proactive: bool = True
    personality: str = "supportive"
    voice_id: str | None = None
    # Off, the partner stops listening but keeps watching and talking; the player types instead.
    mic_enabled: bool = True
    # How much the ElevenLabs voice varies its delivery. "classic" is the original flat sound,
    # kept so the two can be compared by ear.
    voice_style: Literal["expressive", "classic"] = "expressive"
    # How memory finds what the player's words are about. "keyword" matches words, "semantic"
    # matches meaning with a local embedding model, and "hybrid" merges the two.
    memory_search: Literal["keyword", "hybrid", "semantic"] = "keyword"
    pacing: Pacing = Field(default_factory=Pacing)


# --- Brain to overlay ---
class SubtitleChunk(BaseModel):
    type: Literal["subtitle.chunk"] = "subtitle.chunk"
    utterance_id: str
    text: str
    final: bool = False


class AvatarState(BaseModel):
    type: Literal["avatar.state"] = "avatar.state"
    state: Literal["idle", "listening", "talking", "reacting"]


class DangerState(BaseModel):
    """How much trouble the player is in, so the overlay can show it without covering the game.
    Sent when the level changes, and again when the overlay connects."""

    type: Literal["danger.state"] = "danger.state"
    level: Literal["none", "medium", "high"]


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
    """No longer sent: questions are spoken, and the reply is heard or typed like any other turn.
    Kept so an older overlay or recording still validates."""

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


class DebugRegion(BaseModel):
    name: str
    # Overlay window coordinates, like PointerFly.target.
    rect: Rect
    status: Literal["ok", "masked", "unreadable"]
    # What the reader read, such as "72/100" or "62%".
    display: str | None = None


class DebugRegions(BaseModel):
    """A debug view of where each HUD region was found and what its reader reads.

    Always the full current set, so an empty list clears the view. Send it about twice a second
    while debugging: the overlay hides the view when messages stop.
    """

    type: Literal["debug.regions"] = "debug.regions"
    regions: list[DebugRegion]


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


class PlayerText(BaseModel):
    """A turn the player typed in the overlay. The brain handles it exactly like speech."""

    type: Literal["player.text"] = "player.text"
    text: str = Field(min_length=1, max_length=500)


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
    | PageRead
    | DebugRegions
    | DangerState,
    Field(discriminator="type"),
]
OverlayMessage = Annotated[
    OverlayReady
    | OverlayRects
    | CardClosed
    | CardNavigated
    | QuestionAnswer
    | SettingsUpdate
    | PageContent
    | PlayerText,
    Field(discriminator="type"),
]

BrainMessageAdapter: TypeAdapter[BrainMessage] = TypeAdapter(BrainMessage)
OverlayMessageAdapter: TypeAdapter[OverlayMessage] = TypeAdapter(OverlayMessage)

# The Control Center's messages are in control.py, and Protocol, which lists every direction for
# the generated TypeScript, is in __init__.py.
