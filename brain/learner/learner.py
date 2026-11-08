"""Learns where a game's HUD is, by vision, and stores it as data the compiled readers run from.

A pass samples a few gameplay frames, asks vision where the HUD elements are, keeps those that
agree across frames, builds a reader for each, and keeps only readers that read what vision saw.
It runs when nothing has been learned, when the game's size changes, and when readers keep failing.
Vision calls are capped per session, because they share the free tier's quota.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import Event, EventBus, ProfileUpdated, ReadersFailing
from brain.learner.regions import (
    REGION_PROMPT,
    AgreedRegion,
    RegionProposal,
    agree,
    build_spec,
)
from brain.learner.validate import Sample, propose_color, validate
from brain.llm.base import LLMUnavailableError, VisionLLM
from brain.memory.db import Database
from brain.memory.models import GameProfile
from brain.memory.profile import ProfileStore
from brain.perception.closeup import make_closeup
from brain.perception.masking import box_is_masked
from brain.perception.observer import OverlayScale
from brain.perception.ocr import OcrWorker
from brain.perception.profile_schema import LearnedFor, ReaderSpec, Region
from brain.perception.readers import compile_reader, crop_box, learned_size
from shared.protocol import BrainMessage
from shared.protocol.messages import MemoryToast

log = logging.getLogger(__name__)

CHECK_EVERY_S = 5.0
PROPOSAL_MAX_TOKENS = 2000
FRAME_WAIT_S = 60.0
MAX_FRAME_AGE_S = 2.0


@dataclass(frozen=True)
class LearnerConfig:
    frames: int
    frame_gap_s: float
    max_vision_calls: int
    relearn_gap_s: float
    closeup_max_edge_px: int
    mask_padding_px: int
    profile_fixture: Path | None = None


class GameLearner:
    def __init__(
        self,
        database: Database,
        game: str,
        vision: Callable[[], VisionLLM],
        buffer: RingBuffer,
        overlay: OverlayScale,
        bus: EventBus,
        send: Callable[[BrainMessage], Awaitable[None]],
        config: LearnerConfig,
        *,
        ocr: OcrWorker | None = None,
        in_gameplay: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._database = database
        self._game = game
        self._vision = vision
        self._buffer = buffer
        self._overlay = overlay
        self._bus = bus
        self._send = send
        self._config = config
        self._ocr = ocr
        self._in_gameplay = in_gameplay
        self._clock = clock
        self.vision_calls = 0
        self._last_pass_at: float | None = None
        self._readers_failing = False

    async def run(self) -> None:
        events = self._bus.subscribe()
        await self.seed_if_empty()
        while True:
            reason = await self.why_learn(events)
            if reason:
                await self.learn(reason)
            await asyncio.sleep(CHECK_EVERY_S)

    async def _profile(self) -> GameProfile:
        return await self._database.run(lambda conn: ProfileStore(conn).get(self._game))

    async def seed_if_empty(self) -> None:
        """The demo fallback CLAUDE.md allows: only if nothing is learned, and logged loudly."""
        path = self._config.profile_fixture
        if path is None or (await self._profile()).data.get("regions"):
            return
        seed = json.loads(path.read_text(encoding="utf-8"))
        updates = {key: seed[key] for key in ("regions", "readers", "learned_for") if key in seed}
        await self._database.run(lambda conn: ProfileStore(conn).merge_data(self._game, updates))
        log.warning("Using a SEEDED profile from %s. Say so if it's used on stage.", path)
        self._bus.publish(ProfileUpdated(self._game))

    async def why_learn(self, events: "asyncio.Queue[Event]") -> str | None:
        while not events.empty():
            event = events.get_nowait()
            if isinstance(event, ReadersFailing) and event.game == self._game:
                self._readers_failing = True
        now = self._clock()
        if self._last_pass_at is not None and now - self._last_pass_at < self._config.relearn_gap_s:
            return None
        if self.vision_calls >= self._config.max_vision_calls:
            return None
        frame = self._buffer.latest()
        playing = frame is not None and now - frame.ts <= MAX_FRAME_AGE_S and self._in_gameplay()
        if not playing:
            # Nothing to learn from yet, such as before the game starts. Waiting costs nothing.
            return None
        if self._readers_failing:
            return "readers keep failing"
        data = (await self._profile()).data
        if not data.get("regions"):
            return "nothing learned yet"
        learned = learned_size(data)
        if learned and frame is not None:
            height, width = frame.image.shape[:2]
            if (width, height) != (learned.width, learned.height):
                return "the game's size changed"
        return None

    async def learn(self, reason: str) -> bool:
        """One pass. Returns whether anything was learned. Never raises for a vendor failure."""
        self._last_pass_at = self._clock()
        self._readers_failing = False
        calls_before = self.vision_calls
        log.info("Learning where the HUD is (%s)", reason)
        try:
            samples = await self._sample()
            if self.vision_calls == calls_before:
                # Play stopped before anything was spent, so the next chance needn't wait.
                self._last_pass_at = None
        except LLMUnavailableError as exc:
            log.warning("Learning paused: %s", exc)
            return False
        except Exception:
            # Includes a malformed reply: vision output is untrusted, and the observer still covers
            # the HUD, so a failed pass only means trying again later.
            log.exception("A learning pass failed")
            return False
        if len(samples) < 2:
            log.info("Not enough gameplay frames to learn from")
            return False
        kept: list[tuple[Region, ReaderSpec]] = []
        for agreed in agree([proposal for _, proposal in samples]):
            built = await self._build_and_check(agreed, [frame for frame, _ in samples])
            if built:
                kept.append(built)
        if not kept:
            log.info("Learned nothing usable this time; the observer keeps covering the HUD")
            return False
        await self._save(kept, samples[0][0])
        return True

    async def _sample(self) -> list[tuple[Frame, RegionProposal]]:
        samples: list[tuple[Frame, RegionProposal]] = []
        previous: Frame | None = None
        for index in range(self._config.frames):
            if self.vision_calls >= self._config.max_vision_calls:
                log.info("Learner vision budget used up for this session")
                break
            if index:
                await asyncio.sleep(self._config.frame_gap_s)
            frame = await self._gameplay_frame(previous)
            if frame is None:
                break
            previous = frame
            closeup = await asyncio.to_thread(
                make_closeup,
                frame,
                self._overlay.display_scale,
                self._config.mask_padding_px,
                self._config.closeup_max_edge_px,
            )
            self.vision_calls += 1
            proposal = await self._vision().vision_json(
                REGION_PROMPT,
                closeup.image,
                "image/jpeg",
                RegionProposal,
                PROPOSAL_MAX_TOKENS,
                detail="high",
            )
            samples.append((frame, proposal))
        return samples

    async def _gameplay_frame(self, previous: Frame | None) -> Frame | None:
        deadline = self._clock() + FRAME_WAIT_S
        while self._clock() < deadline:
            frame = self._buffer.latest()
            fresh = frame is not None and self._clock() - frame.ts <= MAX_FRAME_AGE_S
            new = frame is not None and (previous is None or frame.ts != previous.ts)
            if fresh and new and self._in_gameplay():
                return frame
            await asyncio.sleep(1.0)
        return None

    async def _build_and_check(
        self, agreed: AgreedRegion, frames: list[Frame]
    ) -> tuple[Region, ReaderSpec] | None:
        region = agreed.region
        samples: list[Sample] = []
        for sighting in agreed.sightings:
            frame = frames[sighting.frame_index]
            if box_is_masked(
                region.box, frame, self._overlay.display_scale, self._config.mask_padding_px
            ):
                continue  # Our own overlay covered it in that frame
            proposal = sighting.proposal
            expected = proposal.fraction_seen if region.kind == "bar" else proposal.text_seen
            samples.append(Sample(crop_box(frame.image, region.box), expected))
        color = None
        if region.kind == "bar" and samples:
            # The fullest sample shows the most of the bar's colour.
            fullest = max(samples, key=lambda s: s.expected if isinstance(s.expected, float) else 0)
            color = propose_color(fullest.crop)
        spec = build_spec(agreed, color)
        if spec is None:
            log.info("No local reader for %s: nothing to read it by", region.name)
            return None
        accepted, why = await validate(compile_reader(spec), samples, self._ocr)
        log.info(
            "Reader %s (%s) %s: %s", spec.name, spec.type, "kept" if accepted else "rejected", why
        )
        return (region, spec) if accepted else None

    async def _save(self, kept: list[tuple[Region, ReaderSpec]], frame: Frame) -> None:
        height, width = frame.image.shape[:2]
        updates = {
            "regions": [region.model_dump() for region, _ in kept],
            "readers": [spec.model_dump() for _, spec in kept],
            "learned_for": LearnedFor(width=width, height=height).model_dump(),
        }
        await self._database.run(lambda conn: ProfileStore(conn).merge_data(self._game, updates))
        self._bus.publish(ProfileUpdated(self._game))
        names = [region.name.replace("_", " ") for region, _ in kept]
        listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        verb = "is" if len(names) == 1 else "are"
        await self._send(MemoryToast(text=f"Learned where your {listed} {verb}", source="observed"))
