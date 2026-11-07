"""Tracks the player's mood from what they say and how they say it, continuously and for free.

Deepgram Flux has no sentiment, and the laptop this runs on is weak, so this uses VADER (a small
word-scoring model) on the live transcript, plus loudness and speech rate for intensity. It's a
rough signal: it misses sarcasm, so it colours the partner's replies and doesn't decide anything.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Game talk that VADER scores as hostile when it's usually neutral or good ("we killed it").
GAME_TALK_NEUTRAL = (
    "kill", "killed", "kills", "killing", "destroy", "destroyed", "destroying", "crushed", "sick",
    "insane", "attack", "attacked", "fight", "fighting", "boss", "shoot", "shot", "enemy",
)  # fmt: skip

NEGATIVE = -0.25
POSITIVE = 0.25
VERY_NEGATIVE = -0.5
HIGH_INTENSITY = 0.5
LOUDNESS_RANGE_DB = 12.0
FAST_SPEECH_WORDS_PER_S = 3.0
MIN_WORDS_FOR_RATE = 3
SILENT_DB = -90.0
# About 200 ms and 10 s at Pipecat's 20 ms audio chunks: the moment against the player's normal.
FAST_LOUDNESS_WEIGHT = 0.1
SLOW_LOUDNESS_WEIGHT = 0.002


@dataclass(frozen=True)
class Mood:
    label: str  # neutral, positive, excited, negative, frustrated or intense
    valence: float  # -1 (negative) to 1 (positive), from the words
    intensity: float  # 0 (calm) to 1 (shouting or rushing), from the voice


def label_mood(valence: float, intensity: float) -> str:
    intense = intensity >= HIGH_INTENSITY
    if valence <= VERY_NEGATIVE or (valence <= NEGATIVE and intense):
        return "frustrated"
    if valence <= NEGATIVE:
        return "negative"
    if valence >= POSITIVE:
        return "excited" if intense else "positive"
    return "intense" if intense else "neutral"


def loudness_db(pcm: bytes) -> float:
    """Loudness of 16-bit audio, in decibels below full scale."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return SILENT_DB
    rms = math.sqrt(float(np.mean(np.square(samples.astype(np.float64)))))
    return 20 * math.log10(rms / 32768) if rms > 0 else SILENT_DB


class MoodTracker:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        min_gap_s: float = 0.5,
        expire_after_s: float = 30.0,
    ) -> None:
        self._clock = clock
        self._min_gap_s = min_gap_s
        self._expire_after_s = expire_after_s
        self._analyzer = SentimentIntensityAnalyzer()
        for word in GAME_TALK_NEUTRAL:
            self._analyzer.lexicon.pop(word, None)
        self._fast_db: float | None = None
        self._normal_db: float | None = None
        self._turn_started = 0.0
        self._last_scored = 0.0
        self._mood: Mood | None = None
        self._mood_at = 0.0

    def start_turn(self) -> None:
        self._turn_started = self._clock()
        self._last_scored = 0.0

    def add_audio(self, pcm: bytes) -> None:
        """Only feed this while the player is talking, or silence would become their normal."""
        level = loudness_db(pcm)
        if self._fast_db is None or self._normal_db is None:
            self._fast_db = self._normal_db = level
            return
        self._fast_db += FAST_LOUDNESS_WEIGHT * (level - self._fast_db)
        self._normal_db += SLOW_LOUDNESS_WEIGHT * (level - self._normal_db)

    def add_text(self, text: str, final: bool = False) -> Mood | None:
        """Scores the turn so far. Returns a mood when it changes or the turn ends."""
        now = self._clock()
        if not text.strip() or (not final and now - self._last_scored < self._min_gap_s):
            return None
        self._last_scored = now
        valence = float(self._analyzer.polarity_scores(text)["compound"])
        intensity = self._intensity(text, now)
        mood = Mood(label_mood(valence, intensity), round(valence, 2), round(intensity, 2))
        changed = self._mood is None or mood.label != self._mood.label
        self._mood, self._mood_at = mood, now
        return mood if changed or final else None

    def live_state(self) -> dict[str, str]:
        """Neutral says nothing, and an old mood shouldn't colour today's reply."""
        mood = self._mood
        if mood is None or mood.label == "neutral":
            return {}
        if self._clock() - self._mood_at > self._expire_after_s:
            return {}
        return {"player mood": mood.label}

    def _intensity(self, text: str, now: float) -> float:
        loud = 0.0
        if self._fast_db is not None and self._normal_db is not None:
            loud = max(0.0, (self._fast_db - self._normal_db) / LOUDNESS_RANGE_DB)
        rushed = 0.0
        words = len(text.split())
        elapsed = now - self._turn_started
        if words >= MIN_WORDS_FOR_RATE and elapsed > 0:
            over = words / elapsed - FAST_SPEECH_WORDS_PER_S
            rushed = max(0.0, over / FAST_SPEECH_WORDS_PER_S) * 0.3
        return min(1.0, loud + rushed)
