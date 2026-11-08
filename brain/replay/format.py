"""The on-disk session format shared by the recorder and replay. See WP3 in REMAINING_WORK.md.

    sessions/<yyyymmdd-hhmmss>-<game-slug>/
      manifest.json      written at the start with complete=false, rewritten at the end
      frames.jsonl       one FrameRecord per line; frames are stored unmasked, with their rects
      frames/000001.jpg
      events.jsonl       one EventRecord per line, including PartnerSaid
      messages.jsonl     one MessageRecord per line: every BrainMessage sent
      audio.wav          optional, 16-bit mono, for reference only

Every `t` is seconds since the recording started. Monotonic timestamps are never stored, because
they mean nothing in another process.
"""

import dataclasses
import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, ValidationError

from brain.events import (
    CardClosedByPlayer,
    CardPageChanged,
    Event,
    GameEvent,
    PlayerMood,
    PlayerSpeech,
    PlayerSpeechPartial,
    PlayerStartedSpeaking,
    QuestionAnswered,
    SettingsChanged,
)
from brain.perception.coords import CropRegion
from shared.protocol.messages import Rect, Settings

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
MANIFEST = "manifest.json"
FRAMES = "frames.jsonl"
FRAMES_DIR = "frames"
EVENTS = "events.jsonl"
MESSAGES = "messages.jsonl"
AUDIO = "audio.wav"

JPEG_QUALITY = 90
# Not a bus event: the partner's accepted lines, which replay feeds to ScriptedTalker instead.
PARTNER_SAID = "PartnerSaid"
# GameEvent sources. Reader events aren't replayed, because readers run again on the frames.
SOURCE_READER = "reader"
SOURCE_REPLAY = "replay"

# Recorded and replayed. OverlayConnected, ProfileUpdated, ReadersFailing and Tick are neither.
_RECORDED: dict[str, type[Event]] = {
    cls.__name__: cls
    for cls in (
        PlayerStartedSpeaking,
        PlayerSpeech,
        PlayerSpeechPartial,
        PlayerMood,
        GameEvent,
        QuestionAnswered,
        CardClosedByPlayer,
        CardPageChanged,
        SettingsChanged,
    )
}


class Manifest(BaseModel):
    format_version: int = FORMAT_VERSION
    game: str
    created_at: str  # Local wall-clock time, ISO 8601, to the second
    display_scale: float = 1.0  # The overlay's, when the rects were recorded
    record_fps: int
    jpeg_quality: int = JPEG_QUALITY
    has_audio: bool = False
    audio_sample_rate: int = 16000
    duration_s: float = 0.0
    dropped_frames: int = 0
    complete: bool = False
    # The overlay settings when recording started, so replay speaks with the same personality.
    settings: dict[str, Any] | None = None


class RegionRecord(BaseModel):
    """A CropRegion: where the frame sits on screen, in physical pixels."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def of(cls, region: CropRegion | None) -> "RegionRecord | None":
        return None if region is None else cls(**dataclasses.asdict(region))

    def to_region(self) -> CropRegion:
        return CropRegion(self.x, self.y, self.width, self.height)


class FrameRecord(BaseModel):
    seq: int
    t: float
    file: str  # Relative to the session directory
    region: RegionRecord | None = None
    overlay_rects: list[Rect] = []  # DIPs, at the manifest's display_scale


class EventRecord(BaseModel):
    t: float
    kind: str  # An Event class name, or PARTNER_SAID
    data: dict[str, Any] = {}


class MessageRecord(BaseModel):
    t: float
    message: dict[str, Any]  # A BrainMessage, as JSON


def frame_file(seq: int) -> str:
    return f"{FRAMES_DIR}/{seq:06d}.jpg"


def session_dir_name(game: str, now: datetime) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-") or "game"
    return f"{now:%Y%m%d-%H%M%S}-{slug}"


def encode_frame(image: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    """JPEG with no chroma subsampling, so thin coloured HUD bars keep their edges for readers."""
    params = [
        cv2.IMWRITE_JPEG_QUALITY,
        quality,
        cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
        cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
    ]
    ok, encoded = cv2.imencode(".jpg", image, params)
    if not ok:
        raise ValueError("Could not encode the frame as JPEG")
    return encoded.tobytes()


def decode_frame(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the frame")
    return image


def event_record(event: Event, t: float) -> EventRecord | None:
    """None for events that aren't recorded."""
    kind = type(event).__name__
    if kind not in _RECORDED:
        return None
    if isinstance(event, SettingsChanged):
        settings = event.settings.model_dump(mode="json")
        return EventRecord(t=t, kind=kind, data={"settings": settings})
    # Monotonic times belong to this process, so they mean nothing in a replay.
    data = {
        f.name: getattr(event, f.name)
        for f in dataclasses.fields(event)
        if f.name not in ("ts", "frame_ts")
    }
    # A JSON round trip turns tuples into lists now, so the record matches what's read back.
    return EventRecord(t=t, kind=kind, data=json.loads(json.dumps(data, default=str)))


def partner_said_record(text: str, t: float) -> EventRecord:
    return EventRecord(t=t, kind=PARTNER_SAID, data={"text": text})


def replay_event(record: EventRecord) -> Event | None:
    """The bus event to publish for a record, or None if replay shouldn't publish it.

    Observer events come back with source "replay". Reader events and PartnerSaid don't come back.
    """
    cls = _RECORDED.get(record.kind)
    if cls is None:
        return None
    data = dict(record.data)
    try:
        if cls is SettingsChanged:
            return SettingsChanged(settings=Settings.model_validate(data["settings"]))
        if cls is GameEvent:
            if data.get("source") == SOURCE_READER:
                return None
            data["source"] = SOURCE_REPLAY
        return cls(**data)
    except (TypeError, KeyError, ValidationError):
        log.warning("Skipping a recorded %s that doesn't fit: %.200s", record.kind, record.data)
        return None


def jsonl_line(record: BaseModel) -> str:
    return record.model_dump_json() + "\n"


def read_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> list[ModelT]:
    """Skips lines that don't parse, such as a last line cut short by a crash. A missing file is
    empty."""
    return list(_iter_jsonl(path, model))


def _iter_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> Iterator[ModelT]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                yield model.model_validate_json(line)
            except ValidationError:
                log.warning("Skipping unreadable line %d of %s", number, path)


def write_manifest(session: Path, manifest: Manifest) -> None:
    """Written to a temporary file first, so a crash mid-write can't leave half a manifest."""
    target = session / MANIFEST
    temporary = target.with_suffix(".tmp")
    temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(target)


def read_manifest(session: Path) -> Manifest:
    """Raises OSError or ValidationError if the manifest is missing or broken."""
    return Manifest.model_validate_json((session / MANIFEST).read_text(encoding="utf-8"))
