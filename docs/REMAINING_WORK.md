# Remaining Work Spec

The inputs, outputs and plug-in points of everything still to build. Each work package (WP) below can be picked up alone, built against fakes and then plugged in with the wiring it lists.

- **Start from:** `main`, which connects everything built so far.
- **Read first:** [CLAUDE.md](../CLAUDE.md) for the rules that must hold, and [DECISIONS.md](DECISIONS.md) for why things are the way they are.
- **What to test:** [TEST_PLAN.md](TEST_PLAN.md). This page doesn't repeat its test lists.
- **Finished work packages** (WP0-WP3, WP6, WP8) moved to [DONE_WORK.md](DONE_WORK.md), which keeps their specs as a record of how that code is meant to work.

Names, signatures and numbers marked as starting values are proposals. If you find a better shape, change it here in the same commit. Anything else on this page describes existing code, checked again on 2026-11-08 at 01:15 against `main` and its uncommitted working tree, plus `origin/wp4-wp5-readers` and the local `perf/voice-path-stalls`.

## Status

**No. The build is not done, and nothing has been proven live over a game.**

| WP | What | Closes | Priority | Track | Needs first |
|---|---|---|---|---|---|
| [WP0](DONE_WORK.md#wp0-shared-contract) | Shared types and file splits | Lets the rest run in parallel | **Done** | Shared | Nothing |
| [WP1](DONE_WORK.md#wp1-test-fakes-and-tests) | Fakes and the tests in the test plan | `CLAUDE.md` testing rule | **Done**, including WP8's tests | All | WP0 |
| [WP2](DONE_WORK.md#wp2-test-tooling) | Typed turns, overlay demo | Testing with no mic | **Done** | Shared, 1 | WP0 |
| [WP3](DONE_WORK.md#wp3-recorder-and-replay) | Recorder and replay | Must-have 8 | **Done.** The reader-event replay check can run now that readers are merged | 2 | WP0 |
| [WP4](#wp4-compiled-readers) | Compiled readers | Must-have 3 | **Merged** from an early snapshot (`bfabbf5`). The live-tested version, with pixel boxes, fill colours and calibration, is on `claude/night`. Health learned live there. Scene matching skipped | 2 | WP0 |
| [WP5](#wp5-learner) | Regions and reader specs. The brief is separate | Must-have 3 | **Regions merged.** Brief stays the deep-model one. Not run live | 4 | WP0, works with WP4 |
| [WP6](DONE_WORK.md#wp6-barks) | Pre-generated bark audio | 300 ms bark budget | **Done** in code and unit tests. The live 300 ms and barge-in checks are not run | 3 | WP0 |
| [WP7](#wp7-measurements-and-decisions) | Measurements and team decisions | Unproven items | **Not done** | All | Keys, a game |
| [WP8](DONE_WORK.md#wp8-reading-the-open-wiki-page) | Answering from the open wiki page | Must-have 6, trusted reads | **Done** in code and unit tests. Stage 1's live page checks are not run | 1, 3, 4 | WP0 |
| [WP9](#wp9-frame-to-voice-latency) | Measure latency from the frame, not the event | Honest numbers for "reacts as it happens" | **Built**, not yet run live. Observer and reader events both carry `frame_ts` | 2, 3 | Nothing |
| [WP10](#wp10-rewind) | Answer "what just happened?" from the last few seconds | The prompt's "over before you could type a prompt" | **Built** in code and unit tests, not yet run live | Shared, 2 | Nothing |
| [WP11](#wp11-proof-benchmarks-and-evals) | Latency report, loop-stall watch, accuracy evals | Numbers for the pitch, and regression checks | **Partly built:** latency report, loop-stall watch and the Control Center's Latency tab. The evals aren't started | All | WP9, a live run |
| [Conditional](#conditional-work) | Only if a test or a decision calls for it | — | **Don't start** | Various | Varies |

Must-haves 1, 2, 4, 5, 6 and 7 are wired on `main` but haven't run live. Must-have 3 (learned regions, then local readers) is merged and not yet run live. WP7 and the test plan's Stages 1-3 are what prove them.

## Before feature freeze

Written 2026-11-08 at 01:00 and checked again at 02:30. Readers are merged. The steps below have not landed. Freeze is about 04:30 and the deadline about 07:30. The prompt is incident.io's: an agent that reacts to a live feed as it happens, with personality.

**Why this order:** readers are merged, and until a profile is learned every game reaction still comes from the Haiku observer. It reports every 1.3 s, two reports must agree, and each takes 1.6-2.7 s, so confirmed events are about 2.4 s old before the talker or TTS start. Nothing has run live over the game.

1. ~~**Push `perf/voice-path-stalls`, then merge it.**~~ Settled: only its vault-export fix was kept, since every role runs on Claude now. All Claude roles also share one connection pool now, which that branch had aimed at.
2. **[WP9](#wp9-frame-to-voice-latency),** so the live run measures the right thing.
3. **Run the test plan's Stages 1-3 over Terraria** with `--record` and the log saved, as [WP11](#wp11-proof-benchmarks-and-evals) describes. The recording is both the benchmark input and the stage fallback.
4. **[WP11](#wp11-proof-benchmarks-and-evals)'s reports** from that run, into the test plan's [Benchmarks](TEST_PLAN.md#4-benchmarks) table.
5. **[WP10](#wp10-rewind),** if there's time before freeze.

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

## WP4: Compiled readers

**Status: merged.** `reader_engine.py`, `reader_rules.py`, `readers.py` and their tests are on `main`. Not run live. Scene matching was the first cut and is not included.

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

**Status: merged.** Regions, reader specs, validation and the seeded profile are on `main` with WP4. The brief the talker reads is still `ask_brief`: once per game, at most 60 words, from the deep model's own knowledge, and never overwritten. `write_brief` remains only for a profile that is still empty once the wiki is known.

**Purpose:** work out where a game's HUD is, by vision, and store that as data. The brief below is the old shape. It is kept so the merge can see what the branch was aiming at.

**Files:** rewrite `brain/learner/learner.py`. New `brain/learner/regions.py` and `brain/learner/validate.py`.

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

### Game brief

Moved out of the learner when main was merged: `ensure_brief` in `brain/game_setup.py` names the game and writes the brief once at startup, from the deep model's general knowledge. The learner no longer writes one from the wiki, so there's one writer.

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

- Boxes that agree become a `Region`. Boxes that don't agree are dropped.
- Conversion from `box_2d` to `Box` is correct.
- A good bar reader is accepted and a wrong one rejected.
- `ProfileUpdated` is published and a toast sent.
- The vision call cap holds, and `LLMUnavailableError` pauses without raising.
- A frame size change triggers another pass.
- A fake `RegionProposal` with injected text can't change anything but stored strings.

**End-to-end check for WP4 and WP5 together:** on synthetic frames with a bar that drops below 25%, the fake learner's region leads to a compiled reader, which raises `health_low` with `source="reader"` and then a bark.

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

## WP9: Frame-to-voice latency

**Status: built, not yet run live.** `GameEvent.frame_ts` is set from the first of the observer's agreeing frames, or the frame a reader read. `brain/latency.py` logs `frame to bark` and `frame to first audio`, split into noticed and spoke.

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

**Status: built in code and unit tests, not yet run live.** `look_back` in `brain/agent/rewind.py` tiles masked frames from 6, 4 and 2 s before the player spoke, and the moment itself, into one sheet of at most 1280 px, built in a worker thread, for one vision call. The tool guidance in `turn.py` says when to use it.

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

**Built, off by default.** Settings > Memory search: Keywords, Both or Meaning. Why and how: [DECISIONS.md](DECISIONS.md#2026-11-08-meaning-based-memory-search-switchable-in-settings).

| | |
|---|---|
| **Files** | `brain/memory/embeddings.py`, `vectors.py`, `recall.py` and `semantic.py`, wired in `service.py` and `brain/app.py` |
| **Model** | fastembed's `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions. Not bge-small, which couldn't separate related questions from unrelated ones |
| **Output** | `vec0` tables `fact_vectors` and `note_vectors`, made at runtime and filled in the background. Recall merges vector hits with FTS5 hits by reciprocal rank fusion |
| **Schema** | No bump. The tables are derived data, rebuilt when the model changes |
| **Budget** | Measured on the main dev machine: `context()` about 4.5 ms in Both, against 1 ms with keywords. Check on the demo machine |
| **Offline** | The first pick downloads the model into `data/models`. Pick Both once before the demo. Any failure falls back to FTS5 |
| **Still to check** | That it finds something keywords miss in a real session. It only helps once memory holds more than the 8 facts the talker always gets |

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
done on main: WP0 WP1 WP2 WP3 WP4 WP5 WP6 WP8, and the brief
then: WP9 → Stages 1-3 → WP11, and WP10 if time
```

**What** `brain/app.py` **gains:**

| WP | New objects | New tasks | On `main`? |
|---|---|---|---|
| WP2 | — | `typed_turns(bus)`, with `--type` | Yes |
| WP3 | `SessionRecorder`, or `ReplayLoop` and `ScriptedTalker` | `recorder.run()` with `--record`. `ReplayLoop` takes `CaptureLoop`'s place | Yes. Construction is in `brain/replay/wiring.py` |
| WP4 | `ReaderEngine` | `readers.run()`. Also `live_state` in `talker_context`, and `suppressed_events` on the observer | Yes, through `build_hud` |
| WP5 | `GameLearner` | `learner.run()`, live only | Yes. Brief: `ensure_brief`, live only |
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
