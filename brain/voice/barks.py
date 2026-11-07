"""Pre-generated lines, so a reaction can skip the model and TTS.

Every fixed line in personalities.json is synthesized once per voice and kept on disk, then held
in RAM so `get` is instant. Generating spends ElevenLabs characters, so it only happens on a cache
miss, one line at a time, in the background.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from brain.director.personalities import LineKind, PersonalityBook

log = logging.getLogger(__name__)

# Voice IDs arrive from the overlay's settings and name a folder, so they must not be a path.
_VOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
ELEVENLABS_URL = "https://api.elevenlabs.io"
SYNTH_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Bark:
    text: str
    pcm: bytes  # 16-bit mono
    sample_rate: int


class BarkSynth(Protocol):
    async def synthesize(self, text: str, voice_id: str, model: str, sample_rate: int) -> bytes:
        """Returns raw 16-bit mono PCM at sample_rate."""
        ...


class ElevenLabsSynth:
    def __init__(self, api_key: str, base_url: str = ELEVENLABS_URL) -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def synthesize(self, text: str, voice_id: str, model: str, sample_rate: int) -> bytes:
        # Imported here so tests and key-less runs don't load Pipecat's ElevenLabs service.
        from pipecat.services.elevenlabs.tts_base import output_format_from_sample_rate

        async with httpx.AsyncClient(timeout=SYNTH_TIMEOUT_S) as client:
            response = await client.post(
                f"{self._base_url}/v1/text-to-speech/{voice_id}",
                params={"output_format": output_format_from_sample_rate(sample_rate)},
                headers={"xi-api-key": self._api_key},
                json={"text": text, "model_id": model},
            )
            response.raise_for_status()
            return response.content


def split_pcm(pcm: bytes, sample_rate: int, chunk_ms: int = 20) -> list[bytes]:
    """Chunks on whole samples, so no chunk splits a 16-bit sample in two."""
    size = max(2, sample_rate * chunk_ms // 1000 * 2)
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]


def _load(paths: dict[str, Path]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for text, path in paths.items():
        try:
            found[text] = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError:
            log.exception("Couldn't read bark %s; it will be generated again", path)
    return found


def _save(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and renamed, so a crash mid-write can't leave a truncated bark to load later.
    partial = path.with_suffix(".part")
    partial.write_bytes(pcm)
    partial.replace(path)


class BarkBank:
    def __init__(
        self,
        book: PersonalityBook,
        synth: BarkSynth | None,
        cache_dir: Path,
        model: str,
        sample_rate: int,
    ) -> None:
        self._book = book
        self._synth = synth
        self._cache_dir = cache_dir
        self._model = model
        self._sample_rate = sample_rate
        self._ready: dict[tuple[str, str], Bark] = {}  # (voice_id, text) -> Bark
        # Startup and every settings change can both ask for a voice, so preparing is serialized.
        self._lock = asyncio.Lock()

    def _texts(self) -> list[str]:
        # Personalities share some lines, and those only need generating once.
        texts = (
            text
            for personality in self._book.personalities.values()
            for lines in personality.lines.values()
            for text in lines
        )
        return list(dict.fromkeys(texts))

    def path(self, voice_id: str, text: str) -> Path:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        # The rate is in the name so a changed tts_sample_rate never plays audio at the wrong speed.
        name = f"{self._model}-{self._sample_rate}-{digest}.pcm"
        return self._cache_dir / voice_id / name

    async def prepare(self, voice_id: str) -> None:
        """Loads from disk and generates what's missing, one at a time.

        Safe to run in the background, and cheap to repeat: lines already in RAM are skipped.
        """
        if not _VOICE_ID.fullmatch(voice_id):
            log.warning("Not preparing barks for an unusable voice ID: %r", voice_id)
            return
        async with self._lock:
            wanted = {
                text: self.path(voice_id, text)
                for text in self._texts()
                if (voice_id, text) not in self._ready
            }
            if not wanted:
                return
            # Off the event loop, because a cold disk shouldn't stall the director.
            found = await asyncio.to_thread(_load, wanted)
            for text, pcm in found.items():
                self._keep(voice_id, text, pcm)
            missing = [text for text in wanted if text not in found]
            made, spent = await self._generate(voice_id, missing)
            log.info(
                "Barks for voice %s: %d from disk, %d generated (%d ElevenLabs characters), "
                "%d still missing",
                voice_id,
                len(found),
                made,
                spent,
                len(missing) - made,
            )

    async def _generate(self, voice_id: str, texts: list[str]) -> tuple[int, int]:
        if not texts or self._synth is None:
            return 0, 0
        made = spent = 0
        for text in texts:
            try:
                pcm = await self._synth.synthesize(text, voice_id, self._model, self._sample_rate)
            except Exception:
                # Usually a bad key or quota, which every other line would hit too. The rest fall
                # back to live TTS, and the next voice change tries again.
                log.exception("Couldn't generate bark %r; stopping for now", text)
                break
            spent += len(text)
            if not pcm:
                log.warning("ElevenLabs returned no audio for bark %r", text)
                continue
            try:
                await asyncio.to_thread(_save, self.path(voice_id, text), pcm)
            except OSError:
                # Still usable this session; it just costs characters again next time.
                log.exception("Couldn't cache bark %r on disk", text)
            self._keep(voice_id, text, pcm)
            made += 1
        return made, spent

    def _keep(self, voice_id: str, text: str, pcm: bytes) -> None:
        if len(pcm) % 2:
            pcm = pcm[:-1]  # A stray byte would shift every later sample
        self._ready[(voice_id, text)] = Bark(text, pcm, self._sample_rate)

    def get(self, personality: str, kind: LineKind, turn: int, voice_id: str) -> Bark | None:
        """Instant, with no I/O. None until that bark is ready."""
        try:
            text = self._book.line(personality, kind, turn)
        except (KeyError, ZeroDivisionError):
            # This personality has no line of that kind, so the caller falls back.
            return None
        return self._ready.get((voice_id, text))
