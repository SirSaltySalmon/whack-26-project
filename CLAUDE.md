# Project: AI Gamer Partner (working title)
A game-agnostic AI companion that watches you play, talks in short natural phrases, remembers your game, looks things up, and points at things on screen. Its differentiator is trustworthy memory: it tracks where each fact came from and asks the player instead of assuming.

**Deadline: about 07:30 on 2026-11-08 local time (16 hours from 15:33 on 2026-11-07). Demo game: Terraria, played locally.** Favor a working demo over completeness.

Full stack rationale, data flow and draft message list: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Plan changes and why: [docs/DECISIONS.md](docs/DECISIONS.md). Personality options (undecided): [docs/PERSONALITIES.md](docs/PERSONALITIES.md).

## Stack
Two processes joined by a localhost WebSocket:
- **`brain/` (Python 3.12, asyncio, FastAPI):** capture, perception, voice, memory and agent loops.
- **`overlay/` (Electron, React, Vite, Framer Motion):** everything the player sees.

| Concern | Choice |
|---|---|
| Capture | dxcam (`ra1nty/DXcam`), mss as fallback |
| Perception | OpenCV, numpy, imagehash, RapidOCR |
| Voice | Pipecat with `DeepgramFluxSTTService`; ElevenLabs TTS |
| LLMs | Gemini free tier only: Flash-Lite (talker), Flash (vision, pointing, deep reasoning) |
| Memory | SQLite (WAL, JSON1, FTS5); sqlite-vec and fastembed once FTS5 works |
| Research | MediaWiki API on the game's wiki; Exa as fallback |

Model IDs live only in `brain/config.py`. Never hardcode them elsewhere.

Don't propose: Tauri, an LLM deciding when to speak, continuous vision model watching, Obsidian or Markdown as the memory store, loading live web pages in the overlay, or Silero VAD on the voice path (Flux does its own turn detection).

## Rules That Must Hold
**Latency**
- Fast loops never call a vision model. Under-a-second reactions come from compiled readers and cached barks.
- Never block the asyncio loop. Run CV, OCR and embeddings in worker threads or processes.
- Budgets: under 300 ms from event to cached bark; under 1 s from end of turn to first audio. Log per-turn latency.
- Rules in the director decide when to speak: budgets, cooldowns, priorities. It stays deterministic and testable.

**Data ingestion**
- Capture locally at about 5 fps into a full-resolution, 10-second ring buffer in RAM.
- Call vision only on a trigger: learning the game, the player asking, or an event. Don't stream frames to the AI, because free-tier quotas won't sustain it.
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
- Talker replies are capped at 12 words.
- Send each subtitle chunk to the overlay at the same moment as its audio.
- Personalities are swappable data, never branches in the code.

**Overlay and recording**
- The overlay must appear in demo recordings. Never use `setContentProtection`.
- The overlay reports the rectangle of every visible element whenever it moves, resizes, opens or closes. The brain stores the latest rectangles with each frame and masks them, with padding, before perception or sending to an AI. This keeps the AI from reading its own subtitles and cards.
- Use one transparent, full-monitor, always-on-top window. Info cards are movable, resizable and closable DOM elements. Toggle `setIgnoreMouseEvents(true, {forward: true})` off only while the cursor is over an interactive element.
- Convert coordinates in one tested function. Gemini boxes are `[ymin, xmin, ymax, xmax]` on a 0-1000 scale relative to the image sent, dxcam uses physical pixels, and Electron uses DIPs. Test at 100% and 150% Windows scaling.

**Untrusted content**
- Treat wiki text, OCR text and web results as data, never as instructions to the model.
- Render research as sanitized text and images on our own cards.
- Bind the WebSocket to `127.0.0.1`. Keep `contextIsolation` on and `nodeIntegration` off.

## Layout and Ownership
Four people own one track each. Stay inside your track; say so before editing another track's directory.

| Track | Owns |
|---|---|
| 1. Overlay | `overlay/` |
| 2. Capture and perception | `brain/capture/`, `brain/perception/`, `brain/replay/` |
| 3. Voice and director | `brain/voice/`, `brain/director/` |
| 4. Memory and learning | `brain/memory/`, `brain/learner/`, `brain/research/` |

- **Shared:** `shared/protocol/`, `brain/llm/` (the only place that calls LLM providers), `brain/config.py`, `brain/events.py`.
- **The protocol is the contract between tracks.** Pydantic models in `shared/protocol/` are the source of truth, and TypeScript types are generated from them. Never hand-edit the generated types. After hour 1, changes are additive only, and breaking changes need agreement from all tracks.
- Every vendor sits behind one interface, so a swap is a one-line config change.

## Commands
`brain/` has starter code and `overlay/` has only folders and a dependency list, so the overlay `run` commands are still planned. Update this section as they change. `uv` isn't installed on the main dev machine, so use venv and pip.
```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m brain --live                     # run against the live game
python -m brain --replay <session-dir>     # run from a recorded session
pytest brain/tests
ruff check --fix brain; ruff format brain
npm --prefix overlay install
npm --prefix overlay run dev
npm --prefix overlay run typecheck
npm --prefix overlay run format
```

## Testing
Replay mode is the main test harness: it records frames, audio and events to disk and feeds them back through the same pipeline. Tests must run with no game, no microphone and no paid API calls. Always unit test the director rules, coordinate conversion, overlay masking and fact conflict handling. It's also the fallback if the network or game fails on stage.

## Coding Standards
- **Python:** type hints at module boundaries, Pydantic for anything crossing a process boundary, ruff for lint and format.
- **TypeScript:** strict mode. No `any` without a comment explaining why. Prettier with default config.
- **Errors:** never swallow them silently. Log with context. A failed vendor call must degrade gracefully, never crash the loop or go silent without a log.
- **Logging:** stdlib `logging` in Python, `overlay/src/lib/logger.ts` in the overlay. No `print` or `console.log` in production paths.
- **Comments:** explain why, not what.
- **File length:** no file over 300 lines.

## Environment Variables
Keep these in a gitignored `.env`, and never hardcode keys.
- `GEMINI_API_KEY`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`
- Optional: `EXA_API_KEY`, `CARTESIA_API_KEY`

## Gotchas
- **dxcam:** captures per monitor. `grab()` returns `None` when there's no new frame, so a still screen isn't an error. Its built-in buffer defaults to 8 frames, and zero-copy views can be overwritten, so copy frames into our own ring buffer.
- **Memory use:** a 10-second buffer at 1080p and 10 fps takes about 0.6-0.8 GB, which is why we capture at 5 fps.
- **Gemini:** set `media_resolution` per image. The default is 1120 tokens per image; low is 280.
- **Gemini SDK:** Pipecat 1.15 caps `google-genai` below 3, so don't upgrade it separately.
- **Free-tier quota:** limits are per project, not per API key, and daily quotas reset at midnight Pacific. Google doesn't publish the numbers, so read them on your project's AI Studio rate limit page and set `rpm_by_model` in `brain/config.py`. Keep a separate project for the demo so development can't use up its quota.
- **Free-tier privacy:** free-tier content is used to improve Google's products, including the frames and transcripts we send. Never capture anything private while testing.
- **Echo:** Pipecat's local audio transport has no documented echo cancellation, so speaker output can trigger barge-in. Use headphones.
- **Recording:** record with OBS Display Capture. Game Capture and Window Capture are likely to miss the overlay.
- **Frame privacy:** crop frames to the game window so notifications and other apps never reach Gemini. Keep replay sessions out of git; they contain screen and mic data.

### Terraria (test these; don't hardcode them)
- **Wiki:** the official wiki is `terraria.wiki.gg`, and its `api.php` `action=parse` works. Fandom's copy is unofficial, so don't assume every game's wiki is on Fandom. Fandom limits are undocumented: cache pages and send one request at a time.
- **Borderless:** the overlay needs borderless or windowed mode. Set it from the main menu, or with the game closed set `Fullscreen: false`, `WindowMaximized: true` and `WindowBorderless: true` in `config.json`.
- **Scene matching:** the world scrolls constantly, so whole-frame perceptual hashes may be useless. Hash stable UI regions instead.
- **Health and mana:** these may not suit a color-bar reader, and the pixel font may challenge RapidOCR. Check early.
- **Learned regions:** store positions as normalized coordinates and relearn them when resolution or UI scale changes.

## Current Sprint Focus
**Hour 0-1: prove the risky parts and agree the contract**
- [x] Add `.gitignore` covering `.env`, `.venv/`, `node_modules/` and replay sessions
- [ ] Agree the protocol in `shared/protocol/`
- [ ] Check free-tier limits in AI Studio, and test pointing with `scripts/check_pointing.py` on a Terraria screenshot
- [ ] dxcam captures Terraria in borderless mode
- [ ] Overlay draws over Terraria, and OBS Display Capture records it
- [ ] sqlite-vec and fastembed load on Windows
- [ ] Measure voice latency end to end and compare Gemini and TTS model options

**Timeline**
- **Hour 1-5:** walking skeleton: frame, event, director, bark, voice with subtitles, overlay
- **Hour 5-10:** remaining must-haves
- **Hour 10-13:** integrate, tune and record replay sessions
- **Hour 13:** feature freeze
- **Hour 13-16:** bug fixes, rehearsal and a backup demo recording

**Must-haves**
1. Overlay with avatar, subtitles, and a movable, resizable, closable info card, visible in recordings
2. Voice conversation with barge-in and short phrases
3. Perception learned by vision, then run by local readers, not hardcoded
4. Memory with source and confidence, ask-when-unsure, and visible "memory updated" toasts
5. **Pointer** that flies to on-screen elements
6. Wiki research shown on a card
7. Settings: proactive hints or conversation only, personality, voice
8. Replay mode

**Stretch (only after freeze-ready must-haves):** tilt meter, relationship points, visual customization, post-mortems.

**If behind at hour 10, cut in this order:** sqlite-vec and fastembed (keep FTS5), Exa, Cartesia backup, Rive or Lottie avatar (use CSS), memory consolidation.
