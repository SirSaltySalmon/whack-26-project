"""All runtime configuration. Model IDs live here and nowhere else."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.protocol.messages import VoiceOption

WS_HOST = "127.0.0.1"  # Localhost only: this socket carries game and player data.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    cartesia_api_key: SecretStr | None = None

    brain_port: int = 8765

    talker_model: str = "gemini-3.5-flash-lite"
    vision_model: str = "gemini-3.6-flash"
    # think_hard and session notes. Paid; falls back to deep_fallback_model without
    # ANTHROPIC_API_KEY. Effort is low, medium or high: medium keeps think_hard to a few seconds.
    deep_model: str = "claude-sonnet-5-5"
    deep_effort: Literal["low", "medium", "high"] = "medium"
    deep_timeout_s: float = 60.0
    deep_fallback_model: str = "gemini-3.6-flash"
    # Reports on what is on screen. Paid, so it only runs with ANTHROPIC_API_KEY set.
    observer_model: str = "claude-haiku-5-5"
    # Answers look_closer while the player waits. Gemini Flash took about 9 s at full
    # resolution, long enough that players talked over it. Falls back to vision_model
    # without ANTHROPIC_API_KEY.
    closeup_model: str = "claude-haiku-5-5"
    # Seconds between screen reports. Low is the default; a boost raises it to medium or high
    # for focus_hold_s, renewed while danger lasts. See brain/perception/focus.py.
    observer_interval_low_s: float = 1.3
    observer_interval_medium_s: float = 0.8
    observer_interval_high_s: float = 0.6
    focus_hold_s: float = 5.0

    # Requests per minute we allow ourselves, per model. These are cautious placeholders: Google
    # doesn't publish free-tier numbers, so set them from your project's AI Studio rate limit page.
    rpm_by_model: dict[str, int] = Field(
        default_factory=lambda: {
            "gemini-3.5-flash-lite": 10,
            "gemini-3.6-flash": 6,
            # One frame per 0.6 s at high focus is 100 a minute, plus look_closer. This is our
            # own spending cap, not a quota.
            "claude-haiku-5-5": 120,
            # Only player-asked think_hard and a note every few minutes; a spending cap.
            "claude-sonnet-5-5": 10,
        }
    )

    tts_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str | None = None
    # Voices offered in the overlay's settings, as JSON: [{"name": "Rachel", "id": "..."}].
    voice_options: list[VoiceOption] = Field(default_factory=list)
    # A hard cap for when the player asks for detail. The prompt keeps replies much shorter.
    talker_max_words: int = 100

    stt_model: str = "flux-general-en"
    # Flux's defaults are 0.7 and 5000 ms. A shorter timeout keeps a trailing "um" from holding
    # the turn open for five seconds.
    stt_eot_threshold: float = 0.7
    stt_eot_timeout_ms: int = 3000
    # Words to boost in transcription, such as boss and item names.
    stt_keyterms: list[str] = Field(default_factory=list)
    # For playing without headphones: mute the mic while the partner talks so it can't hear and
    # interrupt itself. Costs barge-in. The tail covers speaker latency and room echo.
    voice_half_duplex: bool = False
    voice_echo_tail_ms: int = 400
    # PyAudio device indices; None uses the system default.
    mic_device_index: int | None = None
    speaker_device_index: int | None = None

    # The game's process name, such as Terraria. Unset, the player picks the game's window in the
    # terminal at startup (brain/game_setup.py). Live capture stays off until there's one, because
    # capturing without a window to crop to would send the whole desktop onward.
    game_process: str = ""
    capture_fps: int = 5
    ring_buffer_seconds: int = 10
    ai_image_max_edge_px: int = 1280
    mask_padding_px: int = 8
    # For when the player asks for a closer look, which can afford more than the continuous reports.
    closeup_max_edge_px: int = 1920
    # Older frames mean the game isn't in front, so the partner should say it can't see.
    look_max_frame_age_s: float = 15.0
    # Short, because the world may scroll away from whatever was pointed at.
    pointer_ttl_ms: int = 4000

    # The question budget, so asking the player doesn't turn into nagging.
    question_gap_s: float = 90.0
    question_quiet_s: float = 20.0
    # An asked question nobody answers is dropped for good: after this long with no reply started,
    # or after this many player turns that don't answer it. Typed replies get longer.
    question_answer_timeout_s: float = 20.0
    question_typed_timeout_s: float = 45.0
    question_max_turns: int = 2
    # Game-specific questions drafted once per game from the brief, then asked when unknown.
    planned_questions_max: int = 6
    # Unasked-for tips on what to do next, only with hints on. 0 turns them off.
    advice_gap_s: float = 180.0
    advice_quiet_s: float = 20.0
    # The first tip comes sooner than the gap, and sooner again once the partner learns where the
    # player is up to.
    advice_first_s: float = 90.0
    advice_after_learning_s: float = 15.0

    # Names what memory is filed under. It's data, so the brain has no game-specific logic. Unset,
    # the deep model names the game from its window once, and games_path remembers it per app.
    game_title: str = "Unknown game"
    games_path: Path = Path("data/games.json")
    brief_timeout_s: float = 30.0

    db_path: Path = Path("data/brain.sqlite3")
    sessions_dir: Path = Path("sessions")
    # One-way export for reading. SQLite stays the source of truth.
    vault_dir: Path = Path("data/vault")
    replay_snapshot: Path = Path("fixtures/replay_memory.sql")

    note_interval_s: float = 300.0
    note_min_new_events: int = 5

    # Recording a session for replay. Only runs with --record, because it stores screen and mic.
    record_fps: int = 5
    record_max_gb: float = 10.0
    # Replay answers with the recorded lines, so it needs no network. True asks the real talker.
    replay_live_talker: bool = False
    # After the last recorded item, time for the last reply to reach the overlay before exiting.
    replay_exit_grace_s: float = 2.0

    # Compiled readers.
    reader_tick_s: float = 0.2
    reader_failing_after_s: float = 60.0

    # Learning a game's HUD by vision.
    learner_frames: int = 3  # Frames sampled per learning pass
    learner_frame_gap_s: float = 5.0
    learner_max_vision_calls: int = 6  # Per session. Shares Gemini's free-tier quota
    learner_relearn_gap_s: float = 300.0
    # Guessing the player's progress from their gear, when memory doesn't know it.
    progress_max_vision_calls: int = 3  # Per session. Shares Gemini's free-tier quota
    progress_retry_gap_s: float = 120.0
    progress_recheck_s: float = 900.0  # How long a sure guess stands before looking again
    profile_fixture: Path | None = None  # A seeded profile, for the demo fallback only

    # Pre-generated barks.
    barks_dir: Path = Path("data/barks")
    tts_sample_rate: int = 24000  # Pipecat's default output rate
