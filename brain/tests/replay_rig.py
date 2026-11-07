"""Builds tiny recorded sessions on disk, so replay tests need no recorder, game or keys."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from brain.perception.coords import CropRegion
from brain.replay.format import (
    EVENTS,
    FRAMES,
    FRAMES_DIR,
    MESSAGES,
    EventRecord,
    FrameRecord,
    Manifest,
    MessageRecord,
    RegionRecord,
    encode_frame,
    frame_file,
    jsonl_line,
    write_manifest,
)
from shared.protocol.messages import Rect


@dataclass
class RigFrame:
    t: float
    image: np.ndarray
    region: CropRegion | None = None
    rects: Sequence[Rect] = ()


@dataclass
class RigSession:
    frames: list[RigFrame] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    messages: list[MessageRecord] = field(default_factory=list)
    game: str = "Test Game"
    display_scale: float = 1.0
    settings: dict[str, Any] | None = None


def solid_image(fill: int = 128, width: int = 64, height: int = 36) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


def event(t: float, kind: str, **data: Any) -> EventRecord:
    return EventRecord(t=t, kind=kind, data=data)


def message(t: float, **payload: Any) -> MessageRecord:
    return MessageRecord(t=t, message=payload)


def write_session(root: Path, session: RigSession, complete: bool = True) -> Path:
    """Writes `session` under root and returns its directory."""
    directory = root / "20261108-012345-test-game"
    (directory / FRAMES_DIR).mkdir(parents=True)
    frame_lines: list[str] = []
    for seq, frame in enumerate(session.frames, start=1):
        (directory / frame_file(seq)).write_bytes(encode_frame(frame.image))
        record = FrameRecord(
            seq=seq,
            t=frame.t,
            file=frame_file(seq),
            region=RegionRecord.of(frame.region),
            overlay_rects=list(frame.rects),
        )
        frame_lines.append(jsonl_line(record))
    _write_lines(directory / FRAMES, frame_lines)
    _write_lines(directory / EVENTS, (jsonl_line(record) for record in session.events))
    _write_lines(directory / MESSAGES, (jsonl_line(record) for record in session.messages))
    times = [f.t for f in session.frames] + [e.t for e in session.events]
    write_manifest(
        directory,
        Manifest(
            game=session.game,
            created_at=datetime(2026, 11, 8, 1, 23, 45).isoformat(),
            display_scale=session.display_scale,
            record_fps=5,
            duration_s=max(times, default=0.0),
            complete=complete,
            settings=session.settings,
        ),
    )
    return directory


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")
