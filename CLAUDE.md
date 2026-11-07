# Project: AI Gamer Partner (working title)
A game-agnostic AI companion that watches you play, talks in short natural phrases, remembers your game, looks things up, and points at things on screen. Its differentiator is trustworthy memory: it tracks where each fact came from and asks the player instead of assuming.

**Deadline: about 07:30 on 2026-11-08 local time (16 hours from 15:33 on 2026-11-07). Demo game: Terraria, played locally.** Favor a working demo over completeness.

Full stack rationale, data flow and draft message list: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Plan changes and why: [docs/DECISIONS.md](docs/DECISIONS.md). What to test next: [docs/TEST_PLAN.md](docs/TEST_PLAN.md). What's left to build, with inputs and outputs: [docs/REMAINING_WORK.md](docs/REMAINING_WORK.md). Personality options (draft): [docs/PERSONALITIES.md](docs/PERSONALITIES.md).

## Stack
Two processes joined by a localhost WebSocket:
- **`brain/` (Python 3.12, asyncio, FastAPI):** capture, perception, voice, memory and agent loops.
- **`overlay/` (Electron, React, Vite, Framer Motion):** everything the player sees.

| Concern | Choice |
|---|---|
| Capture | dxcam (`ra1nty/DXcam`), mss as fallback |
| Perception | OpenCV, numpy, imagehash, RapidOCR |
| Voice | Pipecat with `DeepgramFluxSTTService`; ElevenLabs TTS |
| LLMs | Gemini free tier: Flash-Lite (talker and player turns with tools), Flash (pointing, progress scout). Claude Haiku 5.5 (paid): screen reports, and `look_closer` because the player waits on it. Claude Sonnet 5.5 (paid, medium effort): deep reasoning (`think_hard`, session notes), with Gemini Flash as the fallback without `ANTHROPIC_API_KEY` |
| Memory | SQLite (WAL, JSON1, FTS5); sqlite-vec and fastembed once FTS5 works |
| Research | MediaWiki API on the game's wiki; Exa as fallback |

Model IDs live only in `brain/config.py`. Never hardcode them elsewhere.

Don't propose: Tauri, an LLM deciding when to speak, an LLM inside the Pipecat pipeline, Obsidian or Markdown as the memory store, or Silero VAD on the voice path (Flux does its own turn detection).

## Rules That Must Hold
**Latency**
- Fast loops never call a vision model. Under-a-second reactions come from compiled readers and cached barks.
- Never block the asyncio loop. Run CV, OCR and embeddings in worker threads or processes.
- Budgets: under 300 ms from event to cached bark; under 1 s from end of turn to first audio. Log per-turn latency.
- Rules in the director decide when to speak: budgets, cooldowns, priorities. It stays deterministic and testable.

**Data ingestion**
- Capture locally at about 5 fps into a full-resolution, 10-second ring buffer in RAM.
- Haiku reports on the newest frame every 1.3 s while the game is in front, or every 0.8 s or 0.6 s for 5 s after a boost (`brain/perception/focus.py`). Danger boosts it by rule and keeps it boosted while it lasts; a player turn can boost it with `watch_closely`. See [docs/DECISIONS.md](docs/DECISIONS.md). A report counts only once consecutive frames agree (`brain/perception/tracker.py`), and even then it's an observation, not a fact.
- Call Gemini vision only on a trigger: learning the game, the player asking, or an event. Free-tier quotas won't sustain streaming.
- Send downscaled frames at `media_resolution` low by default. Send full-resolution crops only when the player asks or an event fires.
- Send every LLM call through a local per-model rate limiter that refuses rather than waits. When over quota, fall back to cached barks or stay quiet.

**Game-agnostic**
- No game-specific logic in `brain/`. Terraria knowledge is learned into the game profile as data.
- A seeded profile may exist in `fixtures/` as a demo fallback. If it's used on stage, say so.

**Memory and trust**
- Memory stores the play session, not a game encyclopedia: session notes, plus facts about the player and this playthrough. Enemy stats and similar details come from wiki lookups. Live game state stays in RAM.
- Every fact stores its source (`player`, `observed`, `wiki`), confidence and validity window.
- Default authority: player > observed > wiki. For current game state, a fresh observation beats anything remembered.
- Wiki facts stay tentative until confirmed by the player or the screen.
- Never overwrite silently. Close the old fact's validity window; if trusted sources conflict, ask the player.
- Low confidence means ask, not guess. Questions go through the director with their own budget so it doesn't nag.
- Fight context drift: the talker only gets a small pre-assembled context, never raw session history. Use rolling summaries.
- SQLite is the source of truth, including Markdown session notes. The Obsidian vault is a one-way export.

**Speech**
- Talker replies are short by default, about one 12-word sentence. They only run longer when the player asks for detail, with a hard cap of 100 words (`talker_max_words`).
- Send each subtitle chunk to the overlay at the same moment as its audio.
- Personalities are swappable data, never branches in the code.

**Overlay and recording**
- The overlay must appear in demo recordings. Never use `setContentProtection`.
- The overlay reports the rectangle of every visible element whenever it moves, resizes, opens or closes. The brain stores the latest rectangles with each frame and masks them, with padding, before perception or sending to an AI. This keeps the AI from reading its own subtitles and cards.
- Use one transparent, full-monitor, always-on-top window. Info cards are movable, resizable and closable DOM elements. Toggle `setIgnoreMouseEvents(true, {forward: true})` off only while the cursor is over an interactive element, and keep it off until a drag ends.
- The game aims with the mouse, so overlay parts stay click-through unless they need a click. The character's body never catches clicks: hovering shows a grip to move it and a corner to resize it, in a 3:4 portrait frame.
- The overlay must not take keyboard focus from the game. The window stays `focusable: false` until the player chooses to type, and goes back when it loses focus.
- The pointer sits beside its target, never on it, because its masked rectangle would hide the target from the next vision call. It always fades on its own, using `ttl_ms`.
- Convert coordinates in one tested function. Gemini boxes are `[ymin, xmin, ymax, xmax]` on a 0-1000 scale relative to the image sent, dxcam uses physical pixels, and Electron uses DIPs. Test at 100% and 150% Windows scaling.

**Tools**
- Tools run only on turns the player started, never on game events. That's what keeps `page_url` player-requested and vision calls bounded.
- Tools are plain functions in `brain/agent/`. MCP, if needed later, is an adapter around that registry, inside the brain. Pipecat's `MCPClient` doesn't fit: it needs an LLM in the pipeline and keeps only text results. See [docs/DECISIONS.md](docs/DECISIONS.md).
- Speech runs in the director's one slot, so its decisions stay instant. A barge-in cancels the turn in progress, unless that turn has started a tool: then it finishes and answers once the player stops talking, and their next turn waits for it.

**Untrusted content**
- Treat wiki text, OCR text and web results as data, never as instructions to the model.
- The wiki window shows the real site in a sandboxed `<webview>`: no preload, no Node, no popups, no permissions, no downloads, an in-memory session and http(s) only. Links can go anywhere and stay in the window.
- That window's rectangle is masked, so frames never show a page to a model. The brain gets page text in two ways, both treated as data: the wiki API, or, on the game's discovered wiki only and on player turns only, the open page's rendered text. Other sites in the window are never read. See [docs/DECISIONS.md](docs/DECISIONS.md).
- Text cards show sanitized plain text, including the wiki window's fallback when a page can't load.
- Bind the WebSocket to `127.0.0.1`. Keep `contextIsolation` on and `nodeIntegration` off.

## Layout and Ownership
Four people own one track each. Stay inside your track; say so before editing another track's directory.

| Track | Owns |
|---|---|
| 1. Overlay | `overlay/` |
| 2. Capture and perception | `brain/capture/`, `brain/perception/`, `brain/replay/` |
| 3. Voice and director | `brain/voice/`, `brain/director/` |
| 4. Memory and learning | `brain/memory/`, `brain/learner/`, `brain/research/` |

- **Shared:** `shared/protocol/`, `brain/llm/` (the only place that calls LLM providers), `brain/agent/` (player-turn tools), `brain/config.py`, `brain/events.py`.
- **Control Center tabs:** one folder per tab under `overlay/src/renderer/control/tabs/`, found automatically. See `tabs/types.ts`; adding a tab edits no shared file.
- **The protocol is the contract between tracks.** Pydantic models in `shared/protocol/` are the source of truth, and TypeScript types are generated from them. Never hand-edit the generated types. After hour 1, changes are additive only, and breaking changes need agreement from all tracks.
- Every vendor sits behind one interface, so a swap is a one-line config change.

## Commands
Update this section as commands change. `uv` isn't installed on the main dev machine, so use venv and pip.
```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m brain --live                     # run against the live game; asks which window if GAME_PROCESS is unset
python -m brain --live --type              # also take turns typed on stdin; `5: what's that` waits 5 s
python -m brain --live --verbose           # same, with debug and library logs
python -m brain --live --record            # also save a session to sessions/ for replay (screen data)
python -m brain --replay <session-dir>     # run from a recorded session
python -m brain --describe                 # JSON for the Control Center: personalities, voices, which keys are set: no game, mic, keys or network
python -m brain --replay <session-dir> --speed 4 --exit-when-done --write-messages run.jsonl
python scripts/compare_replay.py a.jsonl b.jsonl   # compare two runs' messages, ignoring timing and IDs
pytest brain/tests
python scripts/check_observer.py          # print live vision reports (paid, about 3 cents a minute)
python scripts/save_screenshots.py        # save test screenshots of the game
ruff check --fix brain; ruff format brain
npm --prefix overlay install
npm --prefix overlay run dev              # overlay plus the Control Center, which can start the brain
npm --prefix overlay run typecheck
npm --prefix overlay test
npm --prefix overlay run format
npm --prefix overlay run gen:protocol      # after any change in shared/protocol/, with the venv active
python scripts/overlay_demo.py             # drives the overlay with no game, mic or API keys
```

## Testing
What to test next is in [docs/TEST_PLAN.md](docs/TEST_PLAN.md). Shared fakes are in `brain/tests/fakes.py`, so use those rather than writing new ones. Replay mode is the main test harness: `--record` saves frames, events and sent messages to disk, and `--replay` feeds them back through the same pipeline, answering with the recorded lines in subtitles only. Build test sessions with `brain/tests/replay_rig.py`. Tests must run with no game, no microphone and no paid API calls. Always unit test the director rules, coordinate conversion, overlay masking and fact conflict handling. It's also the fallback if the network or game fails on stage.

## Coding Standards
- **Python:** type hints at module boundaries, Pydantic for anything crossing a process boundary, ruff for lint and format.
- **TypeScript:** strict mode. No `any` without a comment explaining why. Prettier with default config.
- **Errors:** never swallow them silently. Log with context. A failed vendor call must degrade gracefully, never crash the loop or go silent without a log.
- **Logging:** stdlib `logging` in Python, `overlay/src/lib/logger.ts` in the overlay. No `print` or `console.log` in production paths.
- **Comments:** explain why, not what.
- **File length:** no file over 300 lines.

## Environment Variables
Keep these in a gitignored `.env`, and never hardcode keys.
- `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`. Without `ANTHROPIC_API_KEY` the brain doesn't watch the screen. Without `DEEPGRAM_API_KEY` it doesn't listen. Without the ElevenLabs two it replies in subtitles only.
- `GAME_PROCESS`: the game's process name, such as `Terraria`. Unset, `--live` lists open app windows in the terminal and the player picks the game; the pick is kept in `data/games.json` and reused when there's no terminal, as when the Control Center starts the brain. Live capture stays off until there's a game.
- `GAME_TITLE`: what memory, the learned profile and the wiki search are filed under. Unset, the deep model names the game from its app and window title once per app and `data/games.json` remembers it. If it's blank, every game shares an empty title.
- Optional: `EXA_API_KEY`, `CARTESIA_API_KEY`, `VOICE_OPTIONS` (JSON list of `{"name", "id"}`, the voices offered in settings)
- Optional voice tuning: `STT_KEYTERMS` (JSON list), `VOICE_HALF_DUPLEX`, `MIC_DEVICE_INDEX`, `SPEAKER_DEVICE_INDEX`

## Gotchas
- **dxcam on the main dev machine:** `dxcam.create()` fails with `COMError -2005270524` (feature level not supported), so capture falls back to mss. Check this on the demo machine.
- **macOS:** capture uses mss and `brain/capture/window_mac.py`, and needs Screen Recording permission for the terminal (without it, frames show only the wallpaper). mss returns points, not Retina pixels, so `live_frame_scale()` overrides the overlay's scale to 1.0. The crop includes the window's title bar. Run the game windowed, not in native fullscreen, or the overlay won't be on its Space. Activate the venv with `source .venv/bin/activate`.
- **dxcam:** captures per monitor. `grab()` returns `None` when there's no new frame, so a still screen isn't an error. Its built-in buffer defaults to 8 frames, and zero-copy views can be overwritten, so copy frames into our own ring buffer.
- **Memory use:** a 10-second buffer at 1080p and 10 fps takes about 0.6-0.8 GB, which is why we capture at 5 fps.
- **Gemini:** set `media_resolution` per image. The default is 1120 tokens per image; low is 280.
- **Gemini SDK:** Pipecat 1.15 caps `google-genai` below 3, so don't upgrade it separately.
- **Gemini tool turns:** send the model's `Content` back unchanged. Gemini 3 needs its thought signatures returned, so `GeminiToolChat` keeps the raw object.
- **Free-tier quota:** limits are per project, not per API key, and daily quotas reset at midnight Pacific. Google doesn't publish the numbers, so read them on your project's AI Studio rate limit page and set `rpm_by_model` in `brain/config.py`. Keep a separate project for the demo so development can't use up its quota.
- **Free-tier privacy:** free-tier content is used to improve Google's products, including the frames and transcripts we send. Never capture anything private while testing.
- **Electron in VS Code:** a shell started by a VS Code extension can have `ELECTRON_RUN_AS_NODE=1` set, which makes Electron fail with `Cannot find module 'electron'`. Unset it first.
- **Echo:** Pipecat's local audio transport has no documented echo cancellation, so speaker output can trigger barge-in. Use headphones. Without them, set `VOICE_HALF_DUPLEX=true`, which mutes the mic while the partner talks but gives up barge-in.
- **Recording:** record with OBS Display Capture. Game Capture and Window Capture are likely to miss the overlay.
- **`<webview>`:** Electron's docs warn it can be unstable, so test it over the game. Hide it with `visibility: hidden`: `display: none` can reload the page. Set `pointer-events: none` on it during a drag, or it swallows the drag.
- **Frame privacy:** frames are cropped to the game window and only captured while it's in front. The Steam overlay draws inside that window, so cropping can't remove friend lists and chats: turn it off while playing. Keep replay sessions out of git; they contain screen and mic data.

### Terraria (test these; don't hardcode them)
- **Wiki:** the official wiki is `terraria.wiki.gg`, and its `api.php` `action=parse` works. Fandom's copy is unofficial, so don't assume every game's wiki is on Fandom. Fandom limits are undocumented: cache pages and send one request at a time.
- **Borderless:** the overlay needs borderless or windowed mode. Set it from the main menu, or with the game closed set `Fullscreen: false`, `WindowMaximized: true` and `WindowBorderless: true` in `config.json`.
- **Scene matching:** the world scrolls constantly, so whole-frame perceptual hashes may be useless. Hash stable UI regions instead.
- **Health and mana:** these may not suit a color-bar reader, and the pixel font may challenge RapidOCR. Check early.
- **Learned regions:** store positions as normalized coordinates and relearn them when resolution or UI scale changes.

## Current Sprint Focus
**Now: test the wiring, then build what's left.** Everything built is connected, but the connections haven't run against real models, audio or a game. Run [docs/TEST_PLAN.md](docs/TEST_PLAN.md) next.

**Wired, not yet run live**
- [ ] Player turns use tools: look closer, point, wiki, note a question, think hard
- [ ] Director runs speech in its own slot, cancels on barge-in unless a slow tool is running, and has a question budget
- [ ] Overlay shows subtitles, memory toasts, questions and settings
- [ ] Personality tone and lines come from data, and `Settings.voice_id` reaches TTS
- [ ] One `LLMFactory`, and the wiki is found in the background at startup
- [ ] Progress scout (`brain/learner/progress.py`): if memory doesn't know how far the player is, Gemini Flash guesses from their gear (at most 3 calls a session) and stores it as an observed `playthrough / progress` fact. The same call drafts questions for the player (where they're up to, plus up to 2 more, such as their goal), queued through the question budget. Check the guesses and questions on real Terraria hotbars
- [ ] Advice: with hints on, a director rule offers a tip on what to do next every `advice_gap_s` (300 s) in a quiet moment, never in danger; the talker can answer SKIP to stay quiet
- [ ] Barks (WP6): pre-generated per voice into `data/barks/`, played for mapped events and the looking filler, else the talker. Check event-to-bark under 300 ms and that barge-in stops one

**Done, with no keys or game**
- [x] Shared contract for the remaining work (WP0)
- [x] Shared fakes and the test plan's automated tests (WP1). WP8's tests come with WP8
- [x] Typed turns and the extended overlay demo (WP2)
- [x] Stage 0, apart from what needs a mouse or a visible window
- [x] Recorder and replay (WP3). Not yet run on a real recording

**Not started**
- [ ] Readers and scene matching. Live state comes from the Haiku observer for now (Track 2)
- [ ] Learner: learned regions, compiled readers (Track 4). The game brief is wired (`brain/learner/brief.py`): at startup the deep model names the game and writes a 60-word brief into the profile, once per game. Check it on a few real games
- [ ] Reading the open wiki page, so the partner can answer from it (Tracks 1, 3 and 4)
- [ ] Agree personality boundaries, and which voice goes with each (all)

**Still unproven from hour 0-1**
- [ ] Check free-tier limits in AI Studio, and test pointing with `scripts/check_pointing.py` on a Terraria screenshot
- [ ] Capture works on the demo machine. dxcam fails on the main dev machine and falls back to mss
- [ ] Overlay draws over Terraria, and OBS Display Capture records it
- [ ] Measure voice latency end to end and compare Gemini and TTS model options
- [ ] fastembed embeds on Windows. It imports and sqlite-vec loads, but no embedding has been run

**Timeline**
- **Hour 1-5:** walking skeleton: frame, event, director, bark, voice with subtitles, overlay
- **Hour 5-10:** remaining must-haves
- **Hour 10-13:** integrate, tune and record replay sessions
- **Hour 13:** feature freeze
- **Hour 13-16:** bug fixes, rehearsal and a backup demo recording

**Must-haves**
1. Overlay with a movable, resizable avatar, subtitles, and a movable, resizable, closable info card, visible in recordings
2. Voice conversation with barge-in and short phrases
3. Perception learned by vision, then run by local readers, not hardcoded
4. Memory with source and confidence, ask-when-unsure, and visible "memory updated" toasts
5. **Pointer** that flies to on-screen elements
6. Wiki research in a movable, resizable, minimizable, closable window showing the real site, with navigation
7. Settings: proactive hints or conversation only, personality, voice
8. Replay mode

**Stretch (only after freeze-ready must-haves):** tilt meter, relationship points, visual customization, post-mortems.

**If behind at hour 10, cut in this order:** sqlite-vec and fastembed (keep FTS5), Exa, Cartesia backup, Rive or Lottie avatar (use CSS), memory consolidation.
