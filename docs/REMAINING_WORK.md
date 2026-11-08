# Remaining Work Spec

The inputs, outputs and plug-in points of everything still to build. Each work package (WP) below can be picked up alone, built against fakes and then plugged in with the wiring it lists.

- **Start from:** the `wiring` branch, which connects everything built so far.
- **Read first:** [CLAUDE.md](../CLAUDE.md) for the rules that must hold, and [DECISIONS.md](DECISIONS.md) for why things are the way they are.
- **What to test:** [TEST_PLAN.md](TEST_PLAN.md). This page doesn't repeat its test lists.

Names, signatures and numbers marked as starting values are proposals. If you find a better shape, change it here in the same commit. Anything else on this page describes existing code, checked again on 2026-11-08 at 01:15 against `main` and its uncommitted working tree, plus `origin/wp4-wp5-readers` and the local `perf/voice-path-stalls`.

## Status

**No. The build is not done, and nothing has been proven live over a game.**

| WP | What | Closes | Priority | Track | Needs first |
|---|---|---|---|---|---|
| [WP0](#wp0-shared-contract) | Shared types and file splits | Lets the rest run in parallel | **Done** | Shared | Nothing |
| [WP1](#wp1-test-fakes-and-tests) | Fakes and the tests in the test plan | `CLAUDE.md` testing rule | **Done**, including WP8's tests | All | WP0 |
| [WP2](#wp2-test-tooling) | Typed turns, overlay demo | Testing with no mic | **Done** | Shared, 1 | WP0 |
| [WP3](#wp3-recorder-and-replay) | Recorder and replay | Must-have 8 | **Done.** The reader-event replay check waits on the WP4 merge | 2 | WP0 |
| [WP4](#wp4-compiled-readers) | Compiled readers | Must-have 3 | **Built, not merged.** On `origin/wp4-wp5-readers`. `main` still has the stub | 2 | WP0 |
| [WP5](#wp5-learner) | Regions and reader specs. The brief is separate | Must-have 3 | **Regions: built, not merged,** on that same branch. **Brief: done** on `main`, in a different shape | 4 | WP0, works with WP4 |
| [WP6](#wp6-barks) | Pre-generated bark audio | 300 ms bark budget | **Done** in code and unit tests. The live 300 ms and barge-in checks are not run | 3 | WP0 |
| [WP7](#wp7-measurements-and-decisions) | Measurements and team decisions | Unproven items | **Not done** | All | Keys, a game |
| [WP8](#wp8-reading-the-open-wiki-page) | Answering from the open wiki page | Must-have 6, trusted reads | **Done** in code and unit tests. Stage 1's live page checks are not run | 1, 3, 4 | WP0 |
| [WP9](#wp9-frame-to-voice-latency) | Measure latency from the frame, not the event | Honest numbers for "reacts as it happens" | **Not started** | 2, 3 | The WP4 merge, for the reader half |
| [WP10](#wp10-rewind) | Answer "what just happened?" from the last few seconds | The prompt's "over before you could type a prompt" | **Not started.** If time before freeze | Shared, 2 | Nothing |
| [WP11](#wp11-proof-benchmarks-and-evals) | Latency report, loop-stall watch, accuracy evals | Numbers for the pitch, and regression checks | **Not started** | All | WP9, a live run |
| [Conditional](#conditional-work) | Only if a test or a decision calls for it | — | **Don't start** | Various | Varies |

Must-haves 1, 2, 4, 5, 6 and 7 are wired on `main` but haven't run live. Must-have 3 (learned regions, then local readers) is the unmerged branch. WP7 and the test plan's Stages 1-3 are what prove the wired ones.

## Before feature freeze

Written 2026-11-08 at 01:00 and checked again at 01:15. None of the steps below have landed. Freeze is about 04:30 and the deadline about 07:30. The prompt is incident.io's: an agent that reacts to a live feed as it happens, with personality.

**Why this order:** on `main`, every game reaction comes from the Haiku observer. It reports every 1.3 s, two reports must agree, and each takes 1.6-2.7 s, so confirmed events are about 2.4 s old before the talker or TTS start. That's the "answer after the fact" the prompt describes. The local readers that fix it are on `origin/wp4-wp5-readers` and are not merged. Nothing has run live over the game.

1. **Commit or set aside the uncommitted work on `main` first.** It is the 2026-11-08 decision (spoken questions, player memory tools, the text box, mic off). It is not committed, and it edits files both merges also edit: `CLAUDE.md`, this file, `docs/DECISIONS.md`, `docs/TEST_PLAN.md`, `brain/memory/service.py`, `brain/config.py`, `brain/perception/observation.py`, `shared/protocol/messages.py` and `overlay/src/renderer/App.tsx`. Merging into this dirty tree will conflict.
2. **Push `perf/voice-path-stalls`, then merge it.** It is one local commit (`17cee42`), not on origin, and not in `main`. It stops 1.7-2 s event-loop freezes after each note, `point_at` and `think_hard`. Conflicts: `brain/memory/service.py`, `brain/tests/test_llm.py`, and `CLAUDE.md`.
3. **Merge `origin/wp4-wp5-readers`** (WP4 and the region half of WP5). Five commits, not in `main`. On `main`, `brain/perception/readers.py` is a 17-line stub and `brain/learner/learner.py` is a 5-line stub. Conflicts: `CLAUDE.md`, `brain/__main__.py`, `brain/app.py`, this file, and `brain/learner/brief.py`, which both sides added, so Track 4 picks one. Main's brief is the one in [WP5](#wp5-learner). Regenerate `protocol.generated.ts` and `schema.json` with `gen:protocol` rather than merging them by hand. Then run the four checks under [Done means](#rules-for-every-work-package).
4. **[WP9](#wp9-frame-to-voice-latency),** so the live run measures the right thing.
5. **Run the test plan's Stages 1-3 over Terraria** with `--record` and the log saved, as [WP11](#wp11-proof-benchmarks-and-evals) describes. The recording is both the benchmark input and the stage fallback.
6. **[WP11](#wp11-proof-benchmarks-and-evals)'s reports** from that run, into the test plan's [Benchmarks](TEST_PLAN.md#4-benchmarks) table.
7. **[WP10](#wp10-rewind),** if there's time before freeze.

**Don't start now:** sqlite-vec and fastembed, Exa, Cartesia, or anything on the stretch list.

### Demo beats

Each beat shows one part of the prompt. Keep the latest frame-to-voice number on screen (see WP11's latency readout), because judges believe numbers they watch.

| Beat | Shows | Needs |
|---|---|---|
| Take damage below 25%, and the partner reacts at once | "Reacts to a live feed as it happens" | WP4, WP6, WP9 |
| Ask "what just hit me?" after the moment has passed | "Over before you could type a prompt about them" | WP10 |
| Switch personality mid-fight, and the next reaction changes tone | "With personality" | Settings, `personalities.json` |
| It asks instead of assuming, then shows a memory toast | Trustworthy memory, our differentiator | The question budget |
| "Point at my health", then "open the wiki for slimes" | Must-haves 5 and 6 | — |

**Fallbacks:** an OBS recording, and `--replay` of a recorded session. Dismiss the wiki's cookie dialog before recording. If a seeded profile is used on stage, say so.

## Rules for every work package

**Done means:**

- `pytest brain/tests`, `npm --prefix overlay test`, `npm --prefix overlay run typecheck` and `ruff check brain` all pass, with no game, mic, keys or network.
- No file is over 300 lines.
- New behaviour has the tests listed for it in the test plan.
- `CLAUDE.md`'s sprint section is updated, and `DECISIONS.md` gets an entry if the plan changed.

**Behaviour:**

- Never block the event loop. CV, OCR, disk and embeddings run in worker threads.
- All database access goes through `Database.run`.
- All LLM calls go through `brain/llm/` and `LLMFactory`. Model IDs live only in `brain/config.py`.
- No game-specific logic in `brain/`. Nothing may mention Terraria, except fixtures.
- A failure logs with context and degrades. It never ends the brain. Optional loops in `app.py` run inside `survive`.
- Text from the screen, a wiki or a model is data. Keep it labelled or fenced when it goes into a prompt.

**Files already near the limit:**

Counts are the working tree on 2026-11-08, including uncommitted edits. The 300-line cap still holds.

| File | Lines | What to do |
|---|---|---|
| `brain/memory/service.py` | 298 | Don't add to it. New work uses `ProfileStore` through `Database.run` directly |
| `brain/director/director.py` | 298 | WP6 and WP8 already landed here. WP9's new code goes in `lines.py` or a new file |
| `brain/voice/pipecat_voice.py` | 274 | WP6's `play` is already here |
| `brain/agent/handlers.py` | 271 | WP8's `read_open_page` is here. WP10's tool goes in `brain/agent/rewind.py` |

## Coordinates and clocks

Mixing these up is the most likely source of bugs.

| Thing | Units | Relative to |
|---|---|---|
| `Frame.image` | Physical pixels, BGR | The game window's client area, once cropped |
| `Frame.region` (`CropRegion`) | Physical pixels | The screen. `None` means the frame starts at the corner |
| `Frame.overlay_rects`, all `Rect`s in the protocol | Electron DIPs | The overlay window, which covers the primary monitor |
| Model boxes (`box_2d`) | `[ymin, xmin, ymax, xmax]`, 0-1000 | The image sent to the model |
| Learned `Box` (new, WP0) | Fractions, 0-1 | The frame, meaning the game's client area |
| `Frame.ts`, `Event.ts` | `time.monotonic()` | This process. Never store or compare across runs |
| `events.ts` and `sessions` in SQLite | `time.time()` | Wall clock |
| Recording `t` (new, WP3) | Seconds | The start of the recording |

The game must be on the primary monitor. Capture and the overlay both assume this, and multi-monitor support isn't planned.

## WP0: Shared contract

**Status: done.** This section now describes existing code. Build against it, and if you change a shape, change it here in the same commit.

**Why:** land these first, in one small commit, so the other work packages can run in parallel without editing the same lines. Everything is additive except the file splits, which change no behaviour.

**What the first version of this spec left open:**

| Added | Why | Who picks it up |
|---|---|---|
| A `Bark` dataclass already exists in `brain/voice/barks.py` | `Voice.play` needs the type now | WP6 adds `BarkSynth` and `BarkBank` beside it |
| `PipecatVoice.play` calls `say(bark.text)` | Every `Voice` has to have `play`, and a bark should arrive late rather than be lost | WP6 replaces it with real playback |
| `decide` already returns `PlayBark` for events in `bark_events`, and `_perform(PlayBark)` falls back to the talker | A `PlayBark` must never be dropped silently. `Director` passes no map yet, so nothing changes today | WP6 adds the map and plays the bark |
| `profile_schema.py` rejects bad values on the way in | It all comes from a vision model, and `compile_profile` skips what fails to validate | WP4 and WP5 |
| A hue range may wrap: `hsv_low` hue above `hsv_high` hue means `H >= low or H <= high` | Reds sit on both sides of 0, and health bars are often red. `cv2.inRange` alone reads a wrapped range as empty | WP4 must honour it, WP5's `propose_color` should use it |

**Bark lines must stay reactions, not advice.** A bark is fixed text, so it can't follow the hints setting the way the talker does. "Your health looks low" is fine, and "find cover" isn't. They also say what it looks like, because the eyes can be wrong.

`brain/events.py`

```python
@dataclass(frozen=True)
class GameEvent(Event):
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    # "observer", "reader" or "replay". Lets replay re-run readers without doubling their events.
    source: str = "observer"

@dataclass(frozen=True)
class ProfileUpdated(Event):
    """The learner saved new regions or readers, so they should be reloaded."""
    game: str

@dataclass(frozen=True)
class ReadersFailing(Event):
    """Learned readers keep failing, so they may be out of date."""
    game: str
    readers: tuple[str, ...]
```

**New** `brain/perception/profile_schema.py`**:** the contract between the learner (writes) and readers (read). It's stored in `profile.data` as three top-level keys, so `ProfileStore.merge_data` can update each one alone.

```python
class Box(BaseModel):
    """Fractions of the frame. Survives resolution changes, as CLAUDE.md requires."""
    x: float; y: float; w: float; h: float        # Each 0-1, and x+w <= 1, y+h <= 1

class Region(BaseModel):
    name: str                                     # "health", "boss_health", "objective"...
    kind: Literal["bar", "number", "text", "stable_ui"]
    box: Box
    confidence: float                             # 0-1, the share of learning frames that agreed

class ColorFillParams(BaseModel):
    hsv_low: tuple[int, int, int]                 # OpenCV ranges: H 0-179, S and V 0-255
    hsv_high: tuple[int, int, int]                # A low hue above the high hue wraps through 0
    axis: Literal["x", "y"] = "x"                 # The direction the bar fills
    reverse: bool = False                         # True if it fills right to left or top down

class OcrParams(BaseModel):
    upscale: int = 3                              # Whole number, nearest-neighbour, for pixel fonts
    min_score: float = 0.6                        # Below this the read counts as unreadable

class EventRule(BaseModel):
    when: Literal["below", "above", "changed"]
    value: float | None = None                    # For below and above
    clear_at: float | None = None                 # Hysteresis: must pass this before firing again
    event: str                                    # The GameEvent name
    confirm_reads: int = 2                        # Consecutive reads before it counts

class ReaderSpec(BaseModel):
    name: str                                     # Unique. Also the default live-state key
    region: str                                   # A Region.name
    type: Literal["color_fill", "ocr_fraction", "ocr_number", "ocr_text"]
    color: ColorFillParams | None = None          # Required for color_fill
    ocr: OcrParams | None = None                  # Required for ocr_*
    rules: list[EventRule] = []
    live_key: str | None = None                   # Defaults to name. None-valued reads stay out
    interval_s: float = 0.2                       # OCR readers should use 0.5 or more

class SceneRef(BaseModel):
    label: str                                    # An Observation.screen_type value
    region: str                                   # A stable_ui Region.name
    phash: str                                    # Hex, from str(imagehash.phash(pil_image))

class LearnedFor(BaseModel):
    width: int; height: int                       # Frame size in physical pixels when learned
```

| `profile.data` key | Type |
|---|---|
| `regions` | `list[Region]`, as JSON |
| `readers` | `list[ReaderSpec]`, as JSON |
| `scenes` | `list[SceneRef]`, as JSON. Optional |
| `learned_for` | `LearnedFor`, as JSON |

`brain/perception/masking.py`**:** add this for WP4, because masks are filled with black and a covered reader must report unknown.

```python
def box_is_masked(box: Box, frame: Frame, display_scale: float, padding_px: int) -> bool:
    """True if any overlay rectangle overlaps this box. Uses frame.overlay_rects and frame.region."""
```

`brain/voice/pipeline.py`**:** add to the `Voice` protocol. `SubtitleOnlyVoice.play` calls `say(bark.text)`.

```python
async def play(self, bark: Bark) -> bool:
    """Plays pre-generated audio. Returns whether it was accepted."""
```

`brain/director/personalities.py` **and** `.json`**:** `LineKind` gains `danger`, `danger_high`, `died` and `low_health`. Each personality gets short lines for them. The JSON gains a top-level map, which is loaded into the book:

```json
"event_lines": { "danger_started": "danger", "danger_high": "danger_high", "player_died": "died", "health_low": "low_health" }
```

`brain/director/rules.py`**:** a new action and state field. An empty map keeps today's behaviour, so existing tests still pass.

```python
@dataclass(frozen=True)
class PlayBark:
    kind: str                       # A LineKind
    event: str                      # The GameEvent name, for logs
    data: dict[str, Any]            # Passed on, in case there's no bark and it falls back

# DirectorState gains:
bark_events: Mapping[str, str] = field(default_factory=dict)   # event name -> LineKind
```

`brain/config.py`, all with these defaults:

```python
record_fps: int = 5
record_max_gb: float = 10.0
reader_tick_s: float = 0.2
reader_failing_after_s: float = 60.0
learner_frames: int = 3             # Frames sampled per learning pass
learner_frame_gap_s: float = 5.0
learner_max_vision_calls: int = 6   # Per session. Shares Gemini's free-tier quota
learner_relearn_gap_s: float = 300.0
barks_dir: Path = Path("data/barks")
tts_sample_rate: int = 24000        # Pipecat's default output rate
profile_fixture: Path | None = None # A seeded profile, for the demo fallback only
```

**File splits, with no behaviour change:**

- `EchoGate`, `TurnBridge` and `SpokenOutputTap` move to `brain/voice/processors.py`.
- Prompts and Pydantic models in `handlers.py` move to `brain/agent/schemas.py`.

**Done when:** the existing tests pass unchanged, except for imports of moved classes.

## WP1: Test fakes and tests

**Status: done.** `test_open_page.py` and the excerpt test in `test_director.py` are written. Where each test lives is in [TEST_PLAN.md section 1](TEST_PLAN.md#1-automated-tests).

**Purpose:** give every other WP the same fakes, so nothing needs keys, then write the tests in the test plan.

**Output:** `brain/tests/fakes.py`. Use these rather than writing new ones.

| Fake | Shape | Records |
|---|---|---|
| `FakeVoice` | `Voice`. `say` returns a settable bool | `said`, `played`, `voice_id` |
| `FakeOverlay` | `display_scale`, `rects`, `async send(message)` | `sent` |
| `FakeVision` | `VisionLLM`. Takes a dict or callable, validated into `schema` | Each call's prompt, image and detail |
| `FakeTextLLM` | `TextLLM`. Streams scripted chunks, or raises | `system`, `prompts` |
| `ScriptedToolLLM` | `ToolLLM`. Takes a list of `ToolStep`s or exceptions | `system`, `tools`, every `send` and `send_results` |
| `FakeMemory` | `wonder`, `take_question`, `record_partner_turn`, `context` | Calls |
| `make_frame(...)` | Builds a `Frame` with a chosen size, age, region and rects | — |
| `make_buffer(*frames)` | Builds a `RingBuffer` | — |

`GeminiClient` can be tested with no network by replacing `client._client` with an object whose `aio.models.generate_content(model, contents, config)` returns `SimpleNamespace(candidates=[SimpleNamespace(content=...)])`.

**Beyond the table:**

- `FakeVoice(accepts=False)` acts like a voice dropping a line because the player is talking. `said` and `played` hold every attempt, accepted or not.
- `ScriptedToolLLM` also takes a coroutine function as a step, for a model that's slow or stuck. `model_calls` counts every call.
- `FakeTextLLM(gate=asyncio.Event())` stays stuck until the gate is set.
- `drain(queue)` returns everything already published to a bus subscription.
- `director_rig.py`, `agent_rig.py` and `fake_gemini.py` set up a real `Director`, a real `AgentTools` and a `GeminiClient` with no network.
- **WP6:** `director_rig.py` sets `director._state.bark_events` directly, because `Director` doesn't take the map as an argument yet. Switch it when that lands.

**Done when:** every test in the test plan exists and passes. Director rules and coordinate tests go first, because `CLAUDE.md` requires them.

## WP2: Test tooling

**Status: done.** How to use both tools is in [TEST_PLAN.md section 2](TEST_PLAN.md#2-test-tooling).

### Typed turns

**Purpose:** test full player turns with no mic or Deepgram key.

| | |
|---|---|
| **Files** | New `brain/voice/typed.py`, plus `brain/__main__.py` and `brain/app.py` |
| **Input** | Lines on stdin. `what's that` runs now. `5: what's that` waits 5 seconds, so there's time to switch back to the game |
| **Output** | Publishes `PlayerStartedSpeaking()`, then on the next loop tick `PlayerSpeech(transcript=...)`. These are the same events real voice sends |

```python
async def typed_turns(bus: EventBus, read_line: Callable[[], str] = input) -> None:
    """Runs read_line off the loop. Returns at end of input. Blank lines are ignored."""

def parse_typed_line(line: str) -> tuple[float, str] | None:
    """Returns (delay_s, transcript), or None for a blank line. Pure, so it's easy to test."""
```

- **Wiring:** `--type` flag, then `tasks.create_task(_survive("Typing", typed_turns(bus)))`.
- **Watch out for:** a thread blocked on `input()` shouldn't hold up Ctrl+C. Use a daemon thread rather than `asyncio.to_thread`.
- **Edge cases, as built:** the space after the colon is what makes a delay, so `12:30 is late` stays a plain sentence. A delay over 300 s counts as part of the sentence, and a delay with nothing after it counts as blank.

### Overlay demo

**File:** `scripts/overlay_demo.py`. Add to the `play()` loop, using the real protocol models:

- `SubtitleChunk` both ways: word chunks followed by an empty final, and one final chunk with all the text
- `MemoryToast` with each source
- `QuestionAsk` with and without options

**Also:** set `link.personalities` and `link.voices` so the settings panel has something to show.

**Done when:** the test plan's Stage 0 can be run from these two tools.

## WP3: Recorder and replay

**Status: done.** This section now describes existing code. Mic audio isn't recorded, and isn't needed: transcripts and mood readings are recorded as events, and replay feeds those back. The recorder can still write `audio.wav` if a hook in `PipecatVoice` ever calls `on_mic_audio`, which would only matter for testing the voice pipeline itself.

**Purpose:** record a session to disk and feed it back through the same pipeline, with no game, mic, keys or network. It's the main test harness.

**Changed while building:**

| Change | Why |
|---|---|
| The manifest stores the overlay `settings` from the start of the recording, and a replayed `SettingsChanged` also updates `link.settings` | The director reads personality and hints from `link.settings`, not from events, so a replay would otherwise speak with whatever settings memory held |
| `partner_lines` leaves out lines that were sent as `question.ask` | The director speaks questions itself, from memory, without the talker. Handing their text to `ScriptedTalker` would shift every later reply |
| `OverlayLink.pinned_display_scale`. Replay pins the recorded scale | Recorded rectangles are in DIPs at the recorded scale. A live overlay connecting mid-replay at another scale would otherwise move every mask |
| Replay speaks in subtitles only, through `SubtitleOnlyVoice`, whatever keys are set | With keys in `.env`, replay would open the real mic and mix live speech into the recording, and spend TTS characters. Word-timed subtitles would also stop two runs comparing equal |
| Replay's session notes get no model (`no_note_model`) | Memory writes a recap with the deep model when a run ends, so a replay with `GEMINI_API_KEY` set would call Gemini. A replay's memory is thrown away anyway |
| Replayed observer events honour `suppressed_events`, like the live observer | Once readers provide an event, a recording made before them would otherwise raise it twice |
| Frames are JPEGs with no chroma subsampling | The default blurs colour edges, which could smear a thin HUD bar for a reader |
| Replay helpers live in `brain/replay/wiring.py`, and the comparison in `brain/replay/compare.py` | Keeps `app.py` near 250 lines, with room for WP4-WP8, and keeps the comparison testable |

**It doesn't show the game by itself.** The overlay would draw over whatever is on screen, and our OpenCV build is headless. The on-stage fallback for the game is still the backup OBS recording. Replay proves the brain's behaviour.

**Files:** `brain/replay/format.py` (the on-disk contract), `recorder.py`, `writer.py` (the writer thread and `MessageLog`), `source.py` (`ReplayLoop`), `scripted.py`, `compare.py` and `wiring.py`. Also `brain/app.py`, `brain/__main__.py`, two hooks in `brain/server.py`, and `scripts/compare_replay.py`.

### Session format

```
sessions/<yyyymmdd-hhmmss>-<game-slug>/
  manifest.json
  frames.jsonl
  frames/000001.jpg ...
  events.jsonl
  messages.jsonl
  audio.wav                (optional)
```

`sessions/` is gitignored and must stay that way, because it holds screen and mic data.

`manifest.json`

```json
{
  "format_version": 1,
  "game": "Terraria",
  "created_at": "2026-11-08T01:23:45",
  "display_scale": 1.5,
  "record_fps": 5,
  "jpeg_quality": 90,
  "has_audio": true,
  "audio_sample_rate": 16000,
  "duration_s": 123.4,
  "dropped_frames": 0,
  "complete": true,
  "settings": {"proactive": true, "personality": "supportive", "voice_id": null}
}
```

Written at the start with `complete: false` and rewritten at the end. A session from a crash stays usable.

`frames.jsonl`, one line per frame. Frames are stored **unmasked, with their rectangles**, so replay exercises the real masking.

```json
{"seq": 12, "t": 2.41, "file": "frames/000012.jpg", "region": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "overlay_rects": [{"x": 24, "y": 800, "width": 150, "height": 200}]}
```

`events.jsonl`, one line per event:

```json
{"t": 3.02, "kind": "PlayerStartedSpeaking", "data": {}}
{"t": 4.40, "kind": "PlayerSpeech", "data": {"transcript": "what's that?"}}
{"t": 6.10, "kind": "GameEvent", "data": {"name": "danger_started", "data": {"level": "high", "threats": ["Slime"]}, "source": "observer"}}
{"t": 6.90, "kind": "PartnerSaid", "data": {"text": "That looks rough."}}
```

| `kind` | Recorded | Replayed |
|---|---|---|
| `PlayerStartedSpeaking`, `PlayerSpeech`, `PlayerSpeechPartial`, `PlayerMood` | Yes | Yes |
| `GameEvent` with `source` `observer` | Yes | Yes, with `source="replay"` |
| `GameEvent` with `source` `reader` | Yes | **No.** Readers run again on the frames, which is the point |
| `QuestionAnswered`, `CardClosedByPlayer`, `CardPageChanged`, `SettingsChanged` | Yes | Yes |
| `OverlayConnected`, `ProfileUpdated`, `ReadersFailing`, `Tick` | No | No |
| `PartnerSaid` (not a bus event) | Yes | Fed to `ScriptedTalker` instead of the bus |

`messages.jsonl` holds every `BrainMessage` sent, as `{"t": 7.1, "message": {...}}`, for comparing runs.

`audio.wav` is 16-bit mono at Pipecat's input rate of 16 kHz. It's for reference and isn't fed back, because transcribing it again would be a paid call. If time is short, this is the first part of WP3 to cut.

### Recorder

```python
class SessionRecorder:
    def __init__(
        self, root: Path, game: str, buffer: RingBuffer, bus: EventBus,
        display_scale: Callable[[], float], record_fps: int, max_gb: float,
    ) -> None: ...

    async def run(self) -> None: ...             # Polls buffer.latest(), consumes its bus queue
    def on_partner_said(self, text: str) -> None: ...
    def on_message(self, message: BrainMessage) -> None: ...
    def on_mic_audio(self, pcm: bytes) -> None: ...
```

| | |
|---|---|
| **Input** | New frames in the ring buffer, its own `bus.subscribe()` queue, and the three hooks |
| **Output** | The session directory |
| **When** | Only with `--record`, because it stores screen and mic data. Never on by default |
| **Threads** | One writer thread. JPEG encoding and disk writes never touch the loop |
| **Overload** | A queue of 32 frames that drops the oldest, counted in `dropped_frames`. Recording must never slow capture |
| **Disk** | Stops saving frames at `record_max_gb` with one warning, and keeps saving events. Expect very roughly 1-2 MB/s at 1080p, which is an estimate to measure |
| **Crash safety** | Flush each JSONL line. Replay ignores a truncated last line |

**Hooks to add:**

- `brain/server.py`: `OverlayLink.on_send: Callable[[BrainMessage], None] | None`, called at the top of `send()` before the connected check. A failing hook logs and the message is still sent.
- `brain/voice/pipecat_voice.py`: **not added.** An optional mic listener called from `on_mic_audio` would fill `audio.wav`. It's Track 3's file, and audio was first to cut.
- `brain/app.py`: wraps `on_spoken` so `recorder.on_partner_said` also runs.

### Replay

```python
class ReplayLoop:
    """Used in place of CaptureLoop. Same async run() shape, so app.py only swaps which it builds."""
    def __init__(
        self, session: Path, buffer: RingBuffer, bus: EventBus, link: OverlayLink,
        speed: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None: ...

    finished: asyncio.Event
    async def run(self) -> None: ...

class ScriptedTalker:
    """A TextLLM that returns the recorded partner lines in order, so replay needs no network."""
    def __init__(self, lines: Sequence[str]) -> None: ...
    def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]: ...
```

| | |
|---|---|
| **Input** | A session directory |
| **Output** | `Frame(ts=clock(), image, overlay_rects, region)` into the ring buffer and recorded events onto the bus, merged in `t` order. Also sets `link.display_scale` from the manifest, and sends recorded `pointer.`* and `card.*` messages so the overlay behaves as it did |
| **Decode** | In a worker thread |
| **Talker** | `ScriptedTalker` by default. A real model only with `REPLAY_LIVE_TALKER=true` |
| **Voice** | `SubtitleOnlyVoice`, always. No mic, no TTS |
| **Scale and settings** | Pins `link.display_scale` to the manifest's, and applies the manifest's settings |
| **Missing or bad session** | Logs and continues without frames, as capture failure does today |

The `ReplayFrameSource` stub goes away, because a `FrameSource` only returns an image and replay needs each frame's recorded region and rectangles.

**CLI:**

```
python -m brain --live --record
python -m brain --replay <session-dir> [--speed 4] [--exit-when-done] [--write-messages out.jsonl]
python scripts/compare_replay.py a/messages.jsonl b/messages.jsonl
```

`compare_replay.py` compares message types and text in order, ignoring timing, IDs and rectangles. It exits non-zero on a difference.

`brain/app.py` **wiring:**

```python
capture = ReplayLoop(replay_dir, buffer, bus, link) if replay_dir else CaptureLoop(...)
talker = ScriptedTalker(partner_lines(replay_dir)) if replay_dir else _talker(factory)
```

The replay rule stays the same: memory starts from `fixtures/replay_memory.sql` in an in-memory database, with no vault export and no observer.

**Done when:**

- [x] A test builds a tiny session in `tmp_path` and replays it at high speed. Frames reach the buffer with their regions, events arrive in order and the fake voice says the recorded lines.
- [x] A replay run with no keys produces the same `messages.jsonl` twice, apart from timing. `test_replay_app.py` records a live run through the real wiring, replays it twice, and checks both against the recording too.
- [ ] A reader's event comes from the frames, not the recording. Recorded reader events are already left out, so this test comes with WP4's readers.
- [x] `look_closer` masking works on replayed frames, with a region offset and 1.5 scaling. Readers on replayed frames come with WP4.

**Watch out for:** a frame is skipped undecoded whenever the next one is already due, so a very high `--speed` drops most frames. Replays meant to exercise readers should use a moderate speed.

**Known limit:** `ScriptedTalker` returns lines in order, so changing director rules can shift which line answers what. Only `compare_replay.py` output needs reviewing in that case.

## WP4: Compiled readers

**Status: built on `origin/wp4-wp5-readers`, not on `main`.** That branch has `reader_engine.py`, `reader_rules.py`, a real `readers.py`, and `test_readers.py`, `test_reader_engine.py` and `test_reader_rules.py`. On `main`, `brain/perception/readers.py` is still the stub protocol below, and nothing publishes reader events. Merge it before treating this section as existing code. Scene matching was the first cut and is not on that branch.

**Purpose:** read HUD values locally, with no model, for reactions under a second. The Haiku observer stays as the source for everything readers don't cover.

**Files:** rewrite `brain/perception/readers.py`. New `brain/perception/reader_engine.py`. The stub's `Reader` protocol has no callers, so it can change.

### Compiling

```python
@dataclass(frozen=True)
class Reading:
    reader: str
    status: Literal["ok", "masked", "unreadable"]
    value: float | str | None     # color_fill and ocr_fraction: 0-1. ocr_number: float. ocr_text: str
    display: str | None           # For live state, such as "72/100" or "62%"

class CompiledReader(Protocol):
    spec: ReaderSpec
    def read(self, crop: np.ndarray) -> Reading:
        """`crop` is BGR, already cropped to the region. Must be safe to call from a worker thread."""

def compile_reader(spec: ReaderSpec) -> CompiledReader: ...
def compile_profile(data: Mapping[str, Any]) -> list[CompiledReader]:
    """Skips and logs any entry that fails to validate. One bad entry can't stop the others."""
```

| Type | How it reads | `value` | `unreadable` when |
|---|---|---|---|
| `color_fill` | Converts to HSV and masks with `hsv_low` to `hsv_high`, as two `inRange` calls when the hue wraps. A column (or row, on axis `y`) counts as filled when at least half its pixels match. The value is the filled run from the start edge, divided by length | 0-1 | No pixels match anywhere, which may mean the bar is gone. Treat an empty bar as `ok` only if `confirm_reads` agree |
| `ocr_fraction` | RapidOCR, then the same `(\d[\d,]*)\s*/\s*(\d[\d,]*)` pattern as `Observation` | current / max | No match, max is 0, or current exceeds max |
| `ocr_number` | RapidOCR, first number | The number | No number |
| `ocr_text` | RapidOCR, joined text | The text | No text above `min_score` |

For RapidOCR, call `RapidOCR()(image, use_cls=False)`. It's expensive to build, so make one per worker. Check the result's text and score fields against the installed 3.10 output class.

### Engine

```python
class ReaderEngine:
    def __init__(
        self, buffer: RingBuffer, overlay: OverlayScale, bus: EventBus,
        load_profile: Callable[[], Awaitable[GameProfile]],
        padding_px: int, tick_s: float, failing_after_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None: ...

    async def run(self) -> None: ...
    def live_state(self) -> dict[str, str]: ...
    def provides(self) -> frozenset[str]:
        """Event names working readers cover, so the observer can leave them to the faster path."""
```

|                  |                                                                                                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**        | The newest frame from `RingBuffer.latest()`, and `profile.data`, loaded at start and again on `ProfileUpdated`                                                      |
| **Output**       | `GameEvent(rule.event, data, source="reader")` on the bus, `live_state()`, `provides()`, and `ReadersFailing`                                                       |
| **Each tick**    | Skip if the frame is unchanged or the last tick hasn't finished. Run due readers in one worker thread. Never queue up work                                          |
| **Masked**       | If `box_is_masked` is true, report `masked` without reading. A masked reader keeps its last value out of live state and fires no rules. It doesn't count as failing |
| **Stale frames** | Older than 2 s means the game isn't in front, so `live_state()` is empty and nothing fires                                                                          |
| **Rules**        | A rule fires after `confirm_reads` consecutive reads, and once only until `clear_at` is passed, like the tracker's low-health logic                                 |
| **Event data**   | Include `{"value": ..., "display": ...}`, plus `{"percent": n}` for fractions. Text values are untrusted and reach the talker as data, as observer text does        |
| `ReadersFailing` | Published once when a reader has been `unreadable` for `failing_after_s`                                                                                            |
| **Budget**       | Log per-tick time. Starting targets: colour under 10 ms, OCR under 150 ms                                                                                           |
| **No profile**   | Sits idle. This is the normal state before learning                                                                                                                 |

**Live state:** use the same keys as the tracker where they mean the same thing, so readers can replace the observer's value. Existing keys are `danger`, `threats`, `health`, `screen`, `notable`, `seen`, `held item`, `location` and `player mood`. Memory caps this block at 340 characters and cuts from the end, so order matters.

`brain/app.py` **wiring:**

```python
readers = ReaderEngine(buffer, link, bus, load_profile, settings.mask_padding_px,
                       settings.reader_tick_s, settings.reader_failing_after_s)
# In talker_context. Mood stays first, and readers overwrite the observer's value for a shared key.
live = {**voice.live_state(), **(observer.live_state() if observer else {}), **readers.live_state()}
tasks.create_task(_survive("Readers", readers.run()))
```

`brain/perception/observer.py`**:** add a keyword argument `suppressed_events: Callable[[], Collection[str]] = frozenset`, and skip publishing those names. The tracker still updates. This stops the slower observer repeating an event a reader already raised.

### Optional inside WP4: scene matching

Cut this first if behind. Whole-frame hashes won't work, because the world scrolls.

- **Input:** `scenes` from the profile, and a `stable_ui` region crop.
- **How:** `imagehash.phash` on the crop, nearest `SceneRef` by Hamming distance, match at 8 or less (starting value).
- **Output:** live-state key `screen`, and `GameEvent("scene_changed", {"from": ..., "to": ...}, source="reader")`.

**Done when**, using synthetic images only (numpy bars, `cv2.putText` numbers), with no fixtures of a real game:

- A bar at 72% reads 0.72 within 0.05, on either axis and in reverse.
- `"72/100"` reads 0.72 when enlarged. Mark OCR tests as slow if needed.
- A masked box gives `masked`, fires nothing and hides the value. A black, unmasked bar isn't reported as masked.
- Rules respect `confirm_reads` and `clear_at`.
- A bad spec is skipped, with the rest still running.
- `ProfileUpdated` reloads.

## WP5: Learner

**Status: split.** The brief is done on `main`, and not in the shape below. `brain/game_setup.py`'s `ensure_brief` calls `ask_brief` in `brain/learner/brief.py` once per game. The deep model names the game and writes at most 60 words from its own knowledge, with no wiki lookup, and it never overwrites a brief. `UNKNOWN` writes nothing.

Regions, reader specs, validation and the seeded profile are on `origin/wp4-wp5-readers` with WP4, not on `main`. `brain/learner/learner.py` on `main` is still the stub. When that branch merges, keep main's brief: both sides added `brief.py`, and main's is the one the talker already reads.

**Purpose:** work out where a game's HUD is, by vision, and store that as data. The brief below is the old shape. It is kept so the merge can see what the branch was aiming at.

**Files:** rewrite `brain/learner/learner.py`. New `brain/learner/brief.py`, `brain/learner/regions.py` and `brain/learner/validate.py`.

### Overview

```python
class GameLearner:
    def __init__(
        self, database: Database, game: str,
        vision: Callable[[], VisionLLM], deep: Callable[[], TextLLM],
        research: Callable[[], WikiResearch | None],
        buffer: RingBuffer, overlay: OverlayScale, bus: EventBus,
        send: Callable[[BrainMessage], Awaitable[None]],
        config: LearnerConfig,
    ) -> None: ...

    async def run(self) -> None: ...
```

- **Stores:** builds its own `ProfileStore` and calls it through `database.run`. It doesn't add to `MemoryService`.
- **Providers:** `vision` and `deep` are callables, because a missing key raises when called. Catch `LLMUnavailableError`, log once and pause.
- `research`**:** `lambda: tools.research`, because the wiki is found in the background.

### Game brief

| | |
|---|---|
| **When** | Once the wiki is available or after 30 s, if `profile.brief` is empty. Never overwrites a brief |
| **Input** | `settings.game_title`, and `WikiCard.context_text()` from `research.lookup(game_title)` if there is one |
| **Call** | `deep().stream_text(system, prompt, max_tokens=300)`. Fence the wiki text as data, the way `notes.py` does with `<<<DATA` and `DATA>>>` |
| **Output** | `ProfileStore.set_brief(game, text)`, at most 300 characters, because the context limit `game_chars` is 300. What the game is, its goals, and its main vocabulary |
| **Without a wiki** | Writes nothing rather than guessing. The title alone isn't enough |
| **Effect** | `gather_context` and `flush_note` already read it, so nothing else needs wiring |

### Regions and reader specs

**Run a learning pass when:**

- `regions` is empty
- the frame size differs from `learned_for`
- `ReadersFailing` arrives, at most once per `learner_relearn_gap_s`

**Steps:**

1. **Sample:** take `learner_frames` frames at least `learner_frame_gap_s` apart. Skip any frame older than 2 s. If there's an observer, wait for `screen` to be `gameplay`.
2. **Ask:** for each frame, call `make_closeup(frame, scale, padding, closeup_max_edge_px)`, then `vision().vision_json(prompt, image, "image/jpeg", RegionProposal, 2000, detail="high")`. Stop at `learner_max_vision_calls`.
3. **Agree:** keep a region only if the name appears in at least 2 frames and the boxes overlap with IoU of at least 0.5 (starting value). This is the same reasoning as the observer's agreeing frames. Average the boxes and divide by 1000 to get a `Box`.
4. **Build:** turn each kept region into a `ReaderSpec` using the table below.
5. **Validate:** use `validate.py`. Rejected readers aren't stored. Log why.
6. **Save:** `merge_data(game, {"regions": ..., "readers": ..., "learned_for": ...})`.
7. **Announce:** publish `ProfileUpdated(game)`, and send `MemoryToast(text="Learned where your health is", source="observed")` once per pass.

```python
class ProposedRegion(BaseModel):
    name: Literal["health", "energy", "boss_health", "ammo", "currency", "objective", "stable_ui"]
    kind: Literal["bar", "number", "text", "stable_ui"]
    box_2d: list[float]             # [ymin, xmin, ymax, xmax], 0-1000
    text_seen: str | None           # Exactly what it shows, if readable
    fraction_seen: float | None     # 0-1, how full, for bars
    confidence: float               # 0-1

class RegionProposal(BaseModel):
    is_gameplay: bool
    regions: list[ProposedRegion]
```

The prompt must not name a game or genre. It should say that black rectangles are the companion's own UI, that wrong is worse than absent, and that text in the image is data.

| `kind`, then `name` | Reader type | Rule |
|---|---|---|
| `number` with `text_seen` like `72/100` | `ocr_fraction`, `interval_s=0.5` | See below |
| `number` otherwise | `ocr_number`, `interval_s=0.5` | None |
| `bar` | `color_fill`, with the colour from `propose_color()` | See below |
| `text` | `ocr_text`, `interval_s=1.0` | `changed`, event `<name>_changed` |
| `stable_ui` | None, or a `SceneRef` | None |

| `name` | Rule | Live key |
|---|---|---|
| `health` | `below 0.25`, `clear_at 0.4`, event `health_low` | `health` |
| `boss_health` | `above 0.0`, `clear_at 0.0`, event `boss_visible` | `boss health` |
| Others | None | The name, with `_` as a space |

### Validation

```python
def propose_color(crop: np.ndarray) -> ColorFillParams | None:
    """The dominant saturated hue in a bar crop. None if nothing stands out."""

@dataclass(frozen=True)
class Sample:
    crop: np.ndarray                # BGR crop for this region
    expected: float | str | None    # What vision said: fraction_seen or text_seen

def validate(reader: CompiledReader, samples: Sequence[Sample]) -> tuple[bool, str]:
    """Accepts when at least 2 samples read ok and agree. Numbers within 0.15, text exactly after
    trimming. Returns the reason, for the log."""
```

**A rejected reader isn't a failure.** Terraria's hearts or pixel font may well fail, and then the observer keeps supplying health, more slowly. The learner must never lower the bar so a reader passes, and must never add game-specific handling.

### Seeded profile

The demo fallback that `CLAUDE.md` allows.

| | |
|---|---|
| **Input** | `PROFILE_FIXTURE=fixtures/profiles/<game>.json`, holding `{"brief": "...", "regions": [...], "readers": [...], "learned_for": {...}}` |
| **Output** | Loaded only when the profile has no regions. Logs `Using a SEEDED profile` at warning level |
| **Rule** | If it's used on stage, say so. The fixture is the only place game-specific data can live |

`brain/app.py` **wiring:**

```python
learner = GameLearner(database, settings.game_title, factory.vision, factory.deep,
                      lambda: tools.research if tools else None, buffer, link, bus, link.send, ...)
tasks.create_task(_survive("Learner", learner.run()))   # Live only, never on replay
```

**Done when**, using `FakeVision`, `FakeTextLLM` and synthetic frames:

- The brief is stored once, fenced, under 300 characters and never overwritten.
- Boxes that agree become a `Region`. Boxes that don't agree are dropped.
- Conversion from `box_2d` to `Box` is correct.
- A good bar reader is accepted and a wrong one rejected.
- `ProfileUpdated` is published and a toast sent.
- The vision call cap holds, and `LLMUnavailableError` pauses without raising.
- A frame size change triggers another pass.
- A fake `RegionProposal` with injected text can't change anything but stored strings.

**End-to-end check for WP4 and WP5 together:** on synthetic frames with a bar that drops below 25%, the fake learner's region leads to a compiled reader, which raises `health_low` with `source="reader"` and then a bark.

## WP6: Barks

**Status: done in code and unit tests.** `BarkBank`, `ElevenLabsSynth` and `PipecatVoice.play` are on `main`. The director plays a bark for a mapped event and for the `looking` filler, and falls back to the talker when none is ready. `test_barks.py` covers the cache, the voice folders and `get` doing no I/O. Not measured: event to bark under 300 ms, and a barge-in stopping one. Those are live checks, in WP7 and WP11. `Latency: event to bark` also starts too late, which is [WP9](#wp9-frame-to-voice-latency).

**Purpose:** speak a short line within 300 ms of an event by skipping the model and TTS. Filler lines and reactions used to go through live TTS, and reactions also through the talker.

**Files:** `brain/voice/barks.py`, which so far only holds `Bark`. Also `brain/voice/pipecat_voice.py`, `brain/director/director.py` and `brain/app.py`. `brain/director/rules.py` is already done: WP0 added `PlayBark` and `bark_events`, and `decide` uses them.

```python
@dataclass(frozen=True)
class Bark:             # Exists already
    text: str
    pcm: bytes          # 16-bit mono
    sample_rate: int

class BarkSynth(Protocol):
    async def synthesize(self, text: str, voice_id: str, model: str, sample_rate: int) -> bytes: ...

class BarkBank:
    def __init__(self, book: PersonalityBook, synth: BarkSynth | None, cache_dir: Path,
                 model: str, sample_rate: int) -> None: ...
    async def prepare(self, voice_id: str) -> None:
        """Loads from disk and generates what's missing, one at a time. Safe to run in the background."""
    def get(self, personality: str, kind: LineKind, turn: int, voice_id: str) -> Bark | None:
        """Instant, with no I/O. None until that bark is ready."""
```

| | |
|---|---|
| **Input** | Every line in `personalities.json`, the voice ID, `tts_model` and `tts_sample_rate` |
| **Output** | `data/barks/<voice_id>/<model>-<sha256(text)[:16]>.pcm`, and `Bark`s in RAM |
| **Synth** | An ElevenLabs HTTP call inside `brain/voice/barks.py`, with `output_format` from `output_format_from_sample_rate`. Pipecat's default output is 24 kHz |
| **Cost** | Generating spends ElevenLabs characters, once per line and voice. After that the disk cache is used. Log the characters spent |
| **When** | In the background at startup for the current voice, and again after `SetVoice`. Never holds up the brain |
| **No key** | `synth=None`, `get` returns `None`, and everything falls back to `say(text)` |

**Director:**

| Case | Behaviour |
|---|---|
| A `GameEvent` named in `bark_events`, not cooling down | `decide` returns `PlayBark(kind, event, data)` |
| `_perform(PlayBark)` with a bark ready | `voice.play(bark)`, then `on_spoken(bark.text)`, and log `Latency: event to bark` using `event.ts` |
| `_perform(PlayBark)` with no bark ready | Falls back to `ReactToEvent(event, data)`, which is today's behaviour |
| The `looking` filler during a tool turn | Uses `voice.play` when a bark is ready, otherwise `say` |

`PlayBark` takes the speech slot like other non-player actions, and a barge-in cancels it.

`PipecatVoice.play`**,** replacing the stub that calls `say`:

- Drop it if the player is speaking, and return `False`, the same as `say`.
- Queue `OutputAudioRawFrame` chunks of about 20 ms through `self._worker.queue_frame`.
- Non-system frames pass through the TTS service behind any queued speech, and the output transport treats them as speech, starting the bot-speaking state. Both come from reading the 1.15 source. **Confirm with a live test that an interruption drops the rest and that** `BotStoppedSpeakingFrame` **fires.**
- Send the subtitle as one `SubtitleChunk(text=bark.text, final=True)` when queuing. `SpokenOutputTap` only sees `TTSTextFrame`, and lines this short don't need word timing.

**Done when:**

- A cache miss generates once. A second `prepare` makes no synth calls.
- `get` does no I/O and returns `None` until ready.
- Changing voice uses the right folder.
- `decide` gives `PlayBark` only for mapped events, respecting the cooldown.
- Falling back with no bark gives the talker path.
- Live: event to bark is under 300 ms, and a barge-in stops it.

## WP7: Measurements and decisions

**Status: not done.** None of the rows below have a recorded result. They need keys and, for the last ones, a game.

Each of these produces a value that goes in one place.

| Task | Input | Output goes in | Decides |
|---|---|---|---|
| Read free-tier limits | AI Studio's rate limit page | `rpm_by_model` in `brain/config.py` | Whether the 10 and 6 requests a minute placeholders are safe |
| Demo Google project | A separate project | Its key in the demo `.env` | Development can't spend the demo's quota |
| Test tool declarations | One real turn | Test plan Stage 1 | Whether Gemini accepts our schemas. If it refuses, fix `ToolRegistry.declarations()` |
| Compare turn models | About 20 varied requests | `talker_model` | If tools are chosen badly, see [Claude for player turns](#claude-for-player-turns) |
| Compare `gemini-3.6-flash` and `3.8-flash` | `scripts/check_pointing.py` on saved screenshots | `vision_model` | Pointing accuracy and speed |
| Compare TTS models | `eleven_flash_v2_5` and `eleven_v4_turbo`, using the logged latency | `tts_model` | Whether the 1 s budget holds |
| Measure voice latency | `Latency:` log lines | Test plan Stage 2 | If over 1 s, see [Reply streaming](#reply-streaming) |
| Capture on the demo machine | `python scripts/check_capture.py` | Test plan Stage 3 | dxcam fails here with `COMError -2005270524`. Is mss fast enough, or does another GPU or session fix it? |
| OBS and overlay over the game | Terraria in borderless mode | Test plan Stage 3 | Whether the demo can be recorded |
| Personality boundaries | Team decision | `personalities.json`, `PERSONALITIES.md` | Limits for Degrading and Romantic, and which voice suits each |
| `VOICE_OPTIONS` | ElevenLabs voice IDs | `.env` | What the settings panel offers |
| Replay memory snapshot | A session you'd be happy to publish, `python -m scripts.snapshot_memory` | `fixtures/replay_memory.sql` | Replay shows the partner remembering. Read it before committing, because it holds transcripts |

## WP8: Reading the open wiki page

**Status: done in code and unit tests, not proven on a real page.** `OpenPage`, `page_match.py`, `page.read` / `page.content`, `read_open_page` and the overlay's isolated-world reader are on `main`. `test_open_page.py` and `test_the_open_page_excerpt_reaches_player_turns_and_never_reactions` cover the done-when list except the Stage 1 checks against a real wiki page. `executeJavaScriptInIsolatedWorld` is what `pageGuard.ts` calls, and it has not been run on a sandboxed `<webview>` over a game. Whether `innerText` still works while the window is minimized is also unchecked.

**Purpose:** let the partner answer from the wiki page the player has open, without a wiki fetch or a vision call, and usually with one Flash-Lite call instead of two. `lookup_wiki` only fetches a page's intro and infobox, and the window is masked, so the rest of an open page would otherwise be out of reach. The decision is in [DECISIONS.md](DECISIONS.md).

**Decided:** rendered text rather than raw HTML, the game's discovered wiki only, and local matching plus a tool.

```
PlayerStartedSpeaking ─► brain: is the open page on the wiki host? ─ no ─► nothing is read
                                         │ yes
                                         ▼
                         page.read ─► overlay ─► main process reads the page ─► page.content ─► RAM
PlayerSpeech ─► match passages locally ─► added to the first prompt ─► usually 1 Flash-Lite call
                                                 not enough ─► read_open_page tool ─► 1 more call
```

Reading at the start of the player's turn means the text and scroll position are fresh, nothing polls, and the voice path never waits, because speech takes far longer than the read. A turn with no snapshot yet carries on without one.

**Files:**

| Track | Files |
|---|---|
| Shared | `shared/protocol/messages.py`, `brain/events.py`, `brain/server.py`, `brain/agent/` |
| 1 | `overlay/src/main/pageGuard.ts`, `overlay/src/main/window.ts`, `overlay/src/lib/bridge.ts`, `overlay/src/preload/index.ts`, `overlay/src/renderer/App.tsx` or a new hook |
| 3 | `brain/director/director.py` |
| 4 | New `brain/research/open_page.py` and `brain/research/page_match.py`, plus `brain/memory/fts.py` |

### Protocol (additive)

```python
class PageRead(BaseModel):                       # Brain to overlay
    type: Literal["page.read"] = "page.read"
    request_id: str

class PageContent(BaseModel):                    # Overlay to brain. Every field is untrusted
    type: Literal["page.content"] = "page.content"
    request_id: str
    card_id: str
    url: str                                     # From WebContents.getURL() at read time
    title: str | None = None
    text: str                                    # Rendered text, at most 200,000 characters
    visible_text: str                            # The part in view, at most 4,000 characters
    truncated: bool = False
```

Add both to the `BrainMessage` and `OverlayMessage` unions, then run `gen:protocol`. In `brain/server.py`, publish `PageContent` as a new event: `PageContentReceived(Event)`, with the same fields.

### Overlay

| | |
|---|---|
| **Input** | `page.read` |
| **Output** | `page.content`, or nothing if there's no window or the read fails or times out after 500 ms. Log why |
| **Bridge** | `readPage(): Promise<PageText \| null>` on `OverlayBridge`, through `ipcRenderer.invoke`. Web pages never get this bridge |
| **Main process** | `guardPage` keeps the page's `WebContents`, and clears it on `destroyed`. It runs the script with `contents.executeJavaScriptInIsolatedWorld(worldId, [{ code }])`, so the page's own scripts can't tamper with it, then adds `contents.getURL()` and `getTitle()` |
| **Sandbox** | Unchanged: no preload, and nothing is injected into the page's own world |

The script must only read:

```js
(() => {
  const root = document.querySelector("#mw-content-text, main, article") ?? document.body;
  const full = root.innerText;
  const inView = (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; };
  const seen = [...root.querySelectorAll("h1,h2,h3,h4,p,li,th,td,dt,dd,figcaption")].filter(inView);
  return {
    text: full.slice(0, 200000),
    visible_text: seen.map((e) => e.innerText).join("\n").slice(0, 4000),
    truncated: full.length > 200000,
  };
})()
```

`innerText` leaves out markup and text hidden by CSS. Form input values aren't part of it.

**To check when building:**

- Whether `executeJavaScriptInIsolatedWorld` works on a sandboxed `<webview>`'s contents. The method is in Electron 45's types, but it hasn't been run.
- Whether `innerText` still works while the window is minimized, because minimizing uses `visibility: hidden`. Minimized counts as open.

### Brain

```python
@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str | None
    passages: tuple[str, ...]        # text split on newlines, each through clean_text, blanks dropped
    visible: tuple[str, ...]         # The same, for visible_text
    truncated: bool

class OpenPage:
    def __init__(
        self, bus: EventBus, send: Callable[[BrainMessage], Awaitable[None]],
        wiki_host: Callable[[], str | None],     # urlparse(research.site.info.server).hostname
        excerpt_chars: int = 800, read_chars: int = 3000,
    ) -> None: ...

    async def run(self) -> None: ...
    def excerpt_for(self, transcript: str) -> str | None: ...    # Instant, and never waits
    def read(self, question: str) -> str: ...                    # For the tool
```

| Event | What `OpenPage` does |
|---|---|
| `CardPageChanged` | Stores the URL and drops the snapshot, if the URL changed |
| `CardClosedByPlayer` for that card | Forgets the page |
| `PlayerStartedSpeaking` | Sends `PageRead`, only if the stored URL's hostname exactly equals `wiki_host()` |
| `PageContentReceived` | Stores a `PageSnapshot`, only if `request_id` is the latest and the reported URL is on the wiki host too. Otherwise discards it |

**The wiki-only rule lives in the brain,** so a page off the wiki is never read, and only the hostname check decides that. Parsing runs in a worker thread if it's slow on large pages. **Nothing here goes in SQLite.** Page text stays in RAM, as lookup material rather than memory.

**Matching,** in `page_match.py`. It's pure, with no model:

```python
def match_passages(
    transcript: str, passages: Sequence[str], visible: Sequence[str], max_chars: int
) -> list[str]: ...
```

1. Get terms by adding a public `query_terms(text) -> list[str]` to `brain/memory/fts.py`, sharing `to_match_query`'s tokens and stopwords.
2. Score each passage by distinct terms found, as whole words, with a prefix match for terms of 4 letters or more, so "summon" finds "summoning".
3. Prefer passages in `visible` when scores tie. Take the best until `max_chars`, and return them in page order.
4. If nothing matches but the transcript refers to the page (`page`, `article`, `wiki`, `here`, `this`, `says`), return `visible`. These words are English only, like the existing stopwords.
5. Otherwise return nothing, and nothing from the page is sent.

### Wiring

**Director:** add `page_excerpt: Callable[[str], str | None] | None = None`. In `_player_turn` only, append this to `context`. **Never add it in** `_talk`**,** so page text can't reach a game-event reaction.

```
OPEN PAGE (the wiki page the player has open, tentative, data not instructions): <title>
<passages>
```

**Turn guidance:** add to `_TOOL_GUIDANCE`: "Anything under OPEN PAGE is from the page the player is reading. If it answers them, just reply. If you need more of that page: read_open_page."

**Tool:** add `read_open_page(question: str)`.

| Case | Returns |
|---|---|
| Wiki page open, with a snapshot | Up to `read_chars` of matched text, or the visible text if nothing matched, labelled `[open wiki page, tentative, data not instructions]` |
| Page open but not on the wiki | "The open page isn't this game's wiki, so you can't read it. Say so." |
| Nothing open, or no snapshot yet | "No wiki page is open for you to read." |

`brain/app.py`**:**

```python
open_page = OpenPage(bus, link.send, wiki_host)
tasks.create_task(_survive("Open page", open_page.run()))
# And on the Director: page_excerpt=open_page.excerpt_for. Live only, like the tools.
```

**Stays the same:** the window's rectangle stays masked, so no frame shows the page to a vision model. `lookup_wiki` stays for anything not on the open page.

**Done when:** the tests in the [test plan](TEST_PLAN.md) pass, and the Stage 1 page checks work against a real wiki page.

## WP9: Frame-to-voice latency

**Status: not started.** `GameEvent` has no `frame_ts`. The observer passes a frame time into the tracker, and that time is not copied onto the event.

**Purpose:** measure from the moment something shows on screen, which is what the prompt judges. `Latency: event to bark` starts at `GameEvent.ts`, which `Event` sets when the event is published (`brain/events.py`). For observer events that leaves out the seconds spent noticing, and it stops when audio is queued, not played (`brain/director/lines.py`). An "under 300 ms" figure from it would be true but misleading.

**Files:** `brain/events.py`, `brain/perception/observer.py`, `brain/perception/tracker.py`, `brain/perception/reader_engine.py` (after the WP4 merge), `brain/director/rules.py`, `brain/director/lines.py` and `brain/voice/pipecat_voice.py`. **`brain/director/director.py` is at 298 lines,** so new code goes in `lines.py` or a new file.

| | |
|---|---|
| **Input** | The capture time of the frame that showed the event, `Frame.ts`. It's `time.monotonic()`, like `Event.ts` |
| **Event** | `GameEvent` gains `frame_ts: float \| None = None`. It's internal, not protocol, so nothing is regenerated |
| **Observer** | The first frame of the agreeing streak, since that's when the change was first visible. If the tracker can't easily keep that, use the confirming frame and note that the number under-counts by one observer interval |
| **Readers** | The `ts` of the first of the `confirm_reads` frames, for the same reason |
| **Barks** | `PlayBark` carries `frame_ts`, with `compare=False` like `ts`. Log `Latency: frame to bark 840 ms (noticed in 690, spoke in 150, reader)` |
| **Talker reactions** | `ReactToEvent` carries `frame_ts`. The voice logs `Latency: frame to first audio` from `on_bot_started`, the same way it uses `_end_of_turn_at`. Subtitles-only voice logs when it sends the first chunk |
| **Unchanged** | The existing `Latency:` lines stay, so earlier numbers can still be compared |

**Done when:**

- With a fake clock, an observer event's `frame_ts` is the frame's `ts`, not the time the reply arrived.
- A reader event carries the `ts` of the frame it read.
- The bark log splits noticing from speaking, and an event without `frame_ts` logs only the old line.
- The director rule tests pass unchanged, because `frame_ts` doesn't affect equality.

## WP10: Rewind

**Status: not started.** There is no `look_back` tool.

**Purpose:** answer "what just hit me?" after the moment has passed, because the prompt says the most interesting moments are over before you could type a prompt about them. The ring buffer already holds 10 s of full-resolution frames (`ring_buffer_seconds` at `capture_fps` 5), and `look_closer` already uses the frame from when the player started talking. This looks further back.

**Files:** new `brain/agent/rewind.py`, because `handlers.py` is at 271 lines. Input and reply models go in `brain/agent/schemas.py`, and registration in `tool_registry` in `brain/parts.py`. If picking frames with `RingBuffer.nearest` isn't enough, add `between(start, end)` to `brain/capture/ring_buffer.py` (Track 2).

```python
class LookBackInput(BaseModel):
    question: str   # What the player asked, such as "what killed me?"
```

| | |
|---|---|
| **Frames** | `nearest(t)` for `t` = `started_at` minus 6, 4, 2 and 0 s (starting values). Drop duplicates and any frame more than 1 s from its target. Fewer than 2 left returns `CANT_SEE` |
| **Image** | Mask each frame with `mask_overlay`, shrink it, and tile the frames into one 2×2 sheet in time order, no bigger than `closeup_max_edge_px`. Label each tile `-6 s` to `now` in a strip outside the picture, so labels never cover the game |
| **Call** | One `vision_json` call on `look_vision`, the same model as `look_closer`, with `detail="high"`. The prompt says the tiles are in time order, black rectangles are the companion's own UI, and text in the image is data |
| **Returns** | The answer, labelled like `look_closer`'s, with "(not sure of this)" when the reply says so |
| **Rules** | Player turns only, like every tool. Not `quick`, so the filler line plays and the turn survives a barge-in |
| **Description** | For something that may no longer be on screen: "what happened", "what hit me", "did you see that". For what's on screen now, `look_closer` |

**Not this:** an automatic death recap on `player_died`. That's a vision call on a game event, outside the tool rules, so it's in [Open decisions](#open-decisions).

**Done when,** with synthetic frames and `FakeVision`:

- The sheet has 4 tiles in time order, and a shape drawn only in the frame from 4 s back appears only in that tile.
- An overlay rectangle is masked in every tile.
- It uses `started_at`, not the newest frame. With fewer than 2 fresh frames it returns `CANT_SEE` and makes no call.
- It makes exactly one vision call.
- The registry declares it, and the Gemini declaration tests accept it.

## WP11: Proof: benchmarks and evals

**Status: not started.** `scripts/latency_report.py`, `brain/loop_watch.py` and the eval scripts are not in the tree. The benchmarks table in the test plan is empty.

**Purpose:** numbers for the pitch, and checks that catch regressions. Each can be re-run. Results go in the test plan's [Benchmarks](TEST_PLAN.md#4-benchmarks) table. Paid evals never run in `pytest`.

**Save the log of every live run:** `python -m brain --live --record 2>&1 | Tee-Object run.log`. Logs are gitignored.

| Item | Files | How | Output |
|---|---|---|---|
| Latency report | New `scripts/latency_report.py` | Parses every `Latency:` line in a saved log | p50, p95, max and count for each kind, with frame-to-voice split by `reader` and `observer`. Prints a Markdown table |
| Loop-stall watch | New `brain/loop_watch.py`, started in `app.py` inside `_survive` | Sleeps 50 ms in a loop and measures how late it wakes | A warning over 100 ms (starting value), and `Event loop: longest stall N ms` at exit. Proves the never-block rule, and would have caught the stalls `perf/voice-path-stalls` fixed. Test it by blocking the loop with `time.sleep` |
| Reader replay benchmark | None expected | Record a session where health falls below 25%. Save the profile with `scripts/export_profile.py`, then replay twice with `PROFILE_FIXTURE`, `--exit-when-done` and `--write-messages` | One `health_low` from `reader`, its frame-to-bark time, and no difference between the runs under `compare_replay.py`. Free and keyless, so re-run it after any perception change. If `PROFILE_FIXTURE` doesn't load in a replay, fix that first |
| Observer eval | New `scripts/eval_observer.py`, labels in `data/eval/observer.json` (gitignored, because they're screenshots) | About 40 screenshots from `save_screenshots.py`, labelled for danger, screen type and health | Accuracy per field, precision and recall for elevated danger, and the two-frame filter's false-alarm rate. Makes the one-off figures in `tracker.py` repeatable. A few cents |
| Tool-choice eval | New `scripts/eval_tools.py` | About 20 requests, each with the tool it should use, or none. Takes the first tool call of one turn and runs nothing | Accuracy for `talker_model`, which answers Stage 1's "picks tools sensibly". About 20 free-tier calls |
| Pointer eval | `scripts/check_pointing.py` over labelled screenshots | Whether each labelled point sits inside the returned box | Hit rate for `vision_model` |
| Soak | A 30-minute live run with the log saved | The latency report and loop-stall watch, plus memory use and calls a minute against `rpm_by_model` | Longest stall, memory growth, cost a minute |
| Latency readout (optional) | New Control Center tab, `overlay/src/renderer/control/tabs/latency/`, found automatically | The Control Center already reads the brain's output lines (`brainProcess.ts`), so it filters the `Latency:` lines. No protocol change | The last few frame-to-voice values on screen during the demo |

## Conditional work

Build these only if a test or decision calls for one. Each has the same no-keys rule.

### Claude for player turns

**If:** Flash-Lite picks tools badly or its quota doesn't hold.

- **File:** `brain/llm/claude.py`. Add `tool_chat()` and `ClaudeToolChat`, implementing `ToolChat`.
- **Input:** the same `system`, `ToolDeclaration`s and results. Map `parameters` to `input_schema`.
- **History:** append `message.content` unchanged as the assistant turn, then all results in **one** user message as `tool_result` blocks with `tool_use_id=call.id`.
- `allow_tools=False`**:** send `tool_choice={"type": "none"}`.
- **Config:** add `agent_provider: Literal["gemini", "claude"]` and `factory.agent()`, then use `factory.agent()` for `agent=` in `app.py`. The talker for game events stays as it is.
- **Note:** `ClaudeClient` sets a 10 s timeout and no retries, which suits frames. Check whether a turn needs different values.

### Reply streaming

**If:** the reply misses the 1 s budget.

- **Input:** `ToolChat` gains a streaming send that yields sentences.
- **Output:** `run_turn` takes an `on_sentence` callback that calls `voice.say` per sentence, and the word cap applies across them.
- **Watch out for:** tool-call parts must still be collected whole, with signatures. A barge-in must cancel the rest, except in a turn that has started a slow tool: its sentences wait for silence instead, like its single reply does now.

### Cartesia backup

**Third on the cut list.**

`CLAUDE.md` says every vendor swaps with one line of config, but TTS doesn't yet: `PipecatVoice` builds `ElevenLabsTTSService` directly.

- **Output:** `create_tts(settings, voice_id) -> TTSService` in `brain/voice/tts.py`, chosen by `tts_provider`, and matching `BarkSynth`s.

### Vector recall

**First on the cut list.**

| | |
|---|---|
| **Files** | New `brain/memory/embeddings.py`, plus `db.py`, `schema.sql` and `gather.py` |
| **Input** | Note bodies and fact text, using fastembed's `BAAI/bge-small-en-v1.5`, 384 dimensions |
| **Output** | `vec0` tables `note_vectors` and `fact_vectors`, filled after writes in a worker. `_recall` merges vector hits with FTS5 hits |
| **Schema** | Bump `SCHEMA_VERSION` to 3. Existing databases must be deleted or migrated, so warn the team |
| **Budget** | `context()` warns over 50 ms, and it's on the voice path. Measure this first on the demo machine. If it's over budget, embed the query in advance from partial transcripts, or leave this out |
| **Offline** | fastembed downloads its model on first use, so it needs caching before a demo. Recall must fall back to FTS5 on any failure |

### Wiki prefetch

**If:** on-demand lookups feel slow.

`WikiResearch.prefetch(queries)` exists but nothing calls it.

- **Input:** threat names from `danger_started` events.
- **Output:** pages in `wiki_cache`, and nothing shown to the player.
- **When:** on `danger_ended`, `player_died` or `scene_changed` to a menu, one at a time, deduplicated, with a cap per session.

### Avatar art

**Near the end of the cut list.** Must-have 1 is met by the placeholder.

- **Input:** `state: State` (`idle`, `listening`, `talking`, `reacting`).
- **Output:** replace `AvatarArt` in `Avatar.tsx`, staying inside the 3:4 frame and click-through.
- **Note:** nothing in the brain sends `reacting` yet. Send `AvatarState("reacting")` from the director when a tool starts or a bark plays.

### MCP adapter

**When something outside the brain needs the tools,** such as Claude Code. See [DECISIONS.md](DECISIONS.md) for why this comes after the registry.

| | |
|---|---|
| **Files** | New `brain/agent/mcp_server.py`, plus `mcp>=2.1.1,<3` in `requirements.txt`, which is the range Pipecat's extra allows. Check it installs alongside the current pins |
| **Input** | `ToolRegistry.declarations()` for listing, and `ToolRegistry.run(call, TurnContext())` for calling |
| **Output** | MCP `tools/list` and `tools/call`, with text content, mounted on the brain's FastAPI app at `/mcp` |
| **Images** | To return frames, change the handler's return from `str` to `ToolOutput(text, images=[...])`, with `images` becoming MCP `ImageContent`. Frames must go through `make_closeup`, so they're always masked |
| **Security** | It serves game frames, so require a bearer token from `.env`, refuse any browser `Origin` as `brain/server.py` does, and stay on `127.0.0.1` |
| **Not this** | Pipecat's `MCPClient`, a separate process, or Anthropic's connector |
| **Rule** | External callers get a tool's effects, so `page_url` needs a decision: only a player turn may open a page |

### Not required

Stretch goals, after freeze-ready must-haves: tilt meter (inputs exist in `PlayerMood` and death events), relationship points, visual customization, and post-mortems (recap notes are the base).

Also unbuilt but not needed for the demo: memory consolidation and profile cleanup.

## Plugging it all in

**Where things stand.** WP0-WP3, WP6 and WP8 are wired on `main`. The brief is wired through `ensure_brief`, not `GameLearner`. WP4 and the region half of WP5 are the unmerged branch. Then WP9, the live run, WP11, and WP10 if there's time.

```
done on main: WP0 WP1 WP2 WP3 WP6 WP8, and the brief
still to merge: WP4 and WP5 regions  (origin/wp4-wp5-readers)
then: WP9 → Stages 1-3 → WP11, and WP10 if time
```

**What** `brain/app.py` **gains:**

| WP | New objects | New tasks | On `main`? |
|---|---|---|---|
| WP2 | — | `typed_turns(bus)`, with `--type` | Yes |
| WP3 | `SessionRecorder`, or `ReplayLoop` and `ScriptedTalker` | `recorder.run()` with `--record`. `ReplayLoop` takes `CaptureLoop`'s place | Yes. Construction is in `brain/replay/wiring.py` |
| WP4 | `ReaderEngine` | `readers.run()`. Also `live_state` in `talker_context`, and `suppressed_events` on the observer | No. On the readers branch |
| WP5 | `GameLearner` | `learner.run()`, live only | Regions: no. Brief: `ensure_brief`, live only |
| WP6 | `BarkBank` | `bank.prepare(voice_id)`. Also `barks=` and `bark_events=` on the `Director` | Yes. Built in `brain/parts.py` |
| WP8 | `OpenPage` | `open_page.run()`, live only. Also `page_excerpt=` on the `Director` | Yes |
| WP10 | — | None. `look_back` joins the registry in `brain/parts.py`, live only like the other tools | No |
| WP11 | — | `loop_watch()`, inside `survive` | No |

`app.py` is 248 lines. Object construction already lives in `brain/parts.py` and `brain/control_wiring.py`. Optional loops run inside `survive`, not `_survive`.

**GameEvent names in use.** Add new ones here. They must describe any game.

| Name | From | `data` |
|---|---|---|
| `danger_started` | Observer | `level`, `threats` |
| `danger_high` | Observer | `threats` |
| `danger_ended` | Observer | — |
| `health_low` | Observer, or a reader | `percent` |
| `player_died` | Observer | — |
| `boss_visible` | Reader (new) | `value`, `display` |
| `<name>_changed` | Reader (new) | `value`, `display`. Text is untrusted |
| `scene_changed` | Reader (new, optional) | `from`, `to` |

The director keys off `danger_started`, `danger_high` and `danger_ended` for its question budget, so keep those names stable.

**Protocol:** only WP8 needs new overlay messages (`page.read` and `page.content`). Changes must stay additive, and regenerate with `npm --prefix overlay run gen:protocol`.

## Open decisions

| Question | Default if nobody decides | Who |
|---|---|---|
| Is the recorded mic needed at all? | **Decided:** it isn't. Transcripts and mood are recorded as events. `audio.wav` was cut | Track 2, in WP3 |
| Does the demo rely on readers, or is the observer enough if readers fail on Terraria? | Observer, and say that readers are what make it faster | Team, after Stage 3 |
| Should `player_died` trigger an automatic "what got you" recap? It's a vision call on a game event, which the tool rules don't allow | No. WP10's rewind runs only when the player asks | Team |
