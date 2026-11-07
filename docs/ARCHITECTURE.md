# Architecture

The system runs as two processes joined by a localhost WebSocket: a **Python brain** and an **Electron overlay**.

Python owns capture, computer vision, voice, memory and the agent loops, because Pipecat, OpenCV, the OCR tools and the vision SDKs all live there. Electron owns everything the player sees, because it's a reliable way to draw a transparent, click-through overlay on top of a game.

Vendor details were checked on 2026-11-07. Re-measure latency on the demo machine rather than trusting these figures.

## Data flow

```
dxcam ─► ring buffer (full-res, 10s) ─┬─► mask overlay rects ─► downscale ─► scene match ─► compiled readers (OCR/colour) ─► EVENT BUS
                                      └─► on demand: masked full-res crop ─────────────────────────────────────────┐
mic ─► Pipecat (Deepgram Flux) ─► transcript / barge-in ─► EVENT BUS                                               │
                                                                                                                   ▼
EVENT BUS ─► DIRECTOR (budgets, cooldowns, priorities) ─┬─► REFLEX: cached bark ─► TTS
                                                        ├─► TALKER: fast LLM ─► TTS (subtitles in step with audio)
                                                        └─► SLOW: Gemini vision (learn regions, answer, point) and post-mortems, consolidation

All paths read and write SQLite: profile, sessions, events, session notes, facts, questions, player, wiki cache
All paths render via WebSocket to the overlay: avatar, pointer, subtitles, cards, "memory updated" toasts
Overlay reports element rectangles back to the brain ─► used for masking
```

## Stack

| Layer | Pick | Why | Rejected |
|---|---|---|---|
| **Overlay / UI** | Electron, React, Vite; Motion for the pointer; Rive or Lottie for the avatar, CSS if short on time | `setIgnoreMouseEvents(true, {forward: true})` makes the overlay click-through but still hoverable, so interaction switches on when the cursor reaches a card. Requires the game in borderless or windowed mode | Tauri (no `forward` option) |
| **Brain** | Python 3.12, asyncio, FastAPI WebSocket | Voice, CV and LLM SDKs in one language and event loop | Node backend (weaker CV and voice ecosystem) |
| **Capture** | dxcam (`ra1nty/DXcam`, wheels for Python 3.10-3.14); mss as fallback | Fast DXGI capture into our own ring buffer, with downscaled copies for the AI | Electron `desktopCapturer` (frames would have to be piped to Python) |
| **Local perception** | OpenCV and numpy for colour readers and frame diffs; `imagehash` for scene matching; RapidOCR | Runs the readers compiled from learned regions, with no LLM | Continuous vision model watching (slow, expensive, fills context) |
| **Voice pipeline** | Pipecat with local audio transport | Easy to inject director events, reports per-turn latency. The pipeline holds no LLM: the director calls the talker and passes text to TTS | LiveKit Agents (turn model tied to LiveKit); Gemini Live and OpenAI Realtime (less control over when it speaks) |
| **STT and end of turn** | Deepgram Flux via `DeepgramFluxSTTService` | Transcription and turn detection in one model. `StartOfTurn` drives barge-in, and `enable_eager_end_of_turn` can cut latency | Nova-3 with Smart Turn; Silero on the voice path (Flux doesn't need it) |
| **TTS** | ElevenLabs: benchmark `eleven_flash_v2_5` against `eleven_v4_turbo`. Cartesia Sonic as optional backup | Both list about 100 ms median, excluding network. ElevenLabs recommends v4 Turbo for real-time use; Flash is cheaper. Pre-generate barks per personality at startup | Hume (stretch only) |
| **Talker LLM** | `gemini-3.5-flash-lite` on the free tier; 12-word cap | Stable and free. The reply is collected up to the cap, then sent to TTS, so the whole reply's time counts toward the 1 s budget and still needs measuring. Small pre-assembled context | Large models on the voice path; paid models (no budget) |
| **Vision and profile learner** | `gemini-3.6-flash` (stable); try `gemini-3.8-flash` (new) | Low resolution by default, full-resolution crops on demand. Structured JSON and pointing coordinates from one provider | Moondream (only if Gemini's coordinates prove too slow) |
| **Deep reasoning** | `gemini-3.6-flash` with higher thinking | Post-mortems, profile cleanup, deciding which questions are worth asking. Latency doesn't matter here, but it shares quota with vision | Claude (no API credits) |
| **Memory** | SQLite in WAL mode with JSON1 and FTS5; then sqlite-vec with fastembed (`BAAI/bge-small-en-v1.5`, 384 dimensions) | Fixed schema with a learned game profile, session notes and a small set of player and playthrough facts. WAL lets fast loops read while the slow loop writes. Local embeddings avoid a network call during recall | Zep, Mem0, Letta (more infrastructure, nowhere to put learned regions) |
| **Web research** | MediaWiki `action=parse` on the game's wiki; Exa as fallback | Researches the title at startup to pre-fill the game brief, then prefetches during downtime. Pages are cached as lookup material, not stored as memory | Perplexity (slow) |
| **Director / event bus** | Plain Python: asyncio queues and a rules module | Deterministic, instant, testable | An LLM deciding when to talk |
| **Tilt meter (stretch)** | Mic loudness and pitch, death streaks, profanity in transcripts | Cheap, and the behavior change is easy to see | Hume in the critical path |
| **Demo safety** | Replay mode recording frames, audio and events | Fallback if the network or game fails on stage, and the main test harness | — |
| **Export** | One-way export of session notes and facts to an Obsidian vault | Shows off what it remembers | Obsidian as the store |

## Overlay and capture

Desktop Duplication captures the whole monitor, so the AI would otherwise read its own subtitles and cards.

Electron's `setContentProtection` isn't used, because it could also remove the overlay from demo recordings. Masking in the brain avoids that risk:

1. The overlay reports element rectangles whenever they move, resize, open or close.
2. The brain converts those rectangles from DIPs to physical pixels, then stores the latest set with each captured frame.
3. Masked areas, with padding, are excluded before perception and before any frame goes to an AI.

Record demos with OBS Display Capture. Check this in the first hour: some OBS users report problems capturing layered or transparent windows.

## Overlay elements

| Element | Behavior |
|---|---|
| **Character** | A 3:4 portrait frame, with a placeholder circle until there's art. Its body stays click-through. Hovering shows a grip to move it, a corner to resize it, and a button to reopen the wiki. Position and size are saved locally, and the brain only sees them through `overlay.rects` |
| **Pointer** | Launches from the character, flies to sit beside the target, shows its label, fades after `ttl_ms` and returns. It doesn't track moving targets, so it points at what it can find on screen |
| **Wiki window** | The real site in a sandboxed `<webview>`, with back, forward, reload, minimize and close. It can be moved and resized. Minimizing shrinks it to a tab near the character and keeps the page and scroll position. There is one wiki window: a new lookup reuses it |
| **Text card** | Sanitized plain text in the same movable, resizable, closable frame |

Only lookups the player asked for send `page_url`, so the partner can't change the page while the player is reading it or cover the game mid-fight. Scrolling and clicking links shouldn't take keyboard focus from the game. Typing into a page needs the player to ask for focus, and the game gets no keys until they click back into it.

If a page can't load, the window shows `body` as text, so research still works without a network.

The overlay checks element rectangles about every 100 ms and reports only changes. Capture runs at about 5 fps, so that's frequent enough, and one check covers drags, animations, opening and closing. A fast drag can show briefly past the mask.

Masks are filled with black, so a reader whose region is under an overlay element must report the value as unknown rather than reading the black pixels.

## Coordinates

Pointing needs one tested conversion path:

```
Gemini box (0-1000, relative to the image sent) ─► crop pixels ─► screen physical pixels ─► Electron DIPs
```

Gemini returns boxes as `[ymin, xmin, ymax, xmax]`. Test at 100% and 150% Windows scaling.

## Memory model

| Table | Holds |
|---|---|
| `profile` | The learned game profile: game brief, regions, readers |
| `sessions` | Each play session of a game |
| `events` | Notable moments and conversation turns, by session |
| `session_notes` | Markdown notes on each session: rolling notes while playing, and a recap at the end |
| `facts` | Claims about the player and this playthrough, with source, confidence and validity window |
| `questions` | Open and answered clarifying questions, linked to the facts they settle |
| `player` | Preferences and settings |
| `wiki_cache` | Fetched wiki pages. This is lookup material, not memory |

Live game state stays in RAM with the readers, so a fresh value always reaches the talker.

SQLite is the source of truth. Notes and facts are exported one way to an Obsidian vault for reading, so edits made in the vault don't flow back.

Trust rules are in [CLAUDE.md](../CLAUDE.md#rules-that-must-hold). The reasoning behind this model is in the [decision log](DECISIONS.md).

## Wiki research

The research client takes any MediaWiki `api.php` base URL, so it isn't tied to Fandom. Finding a game's wiki from its title is still an open problem, because research turned up no documented Fandom lookup.

A sensible order is to try known wiki hosts (wiki.gg, then Fandom), then fall back to Exa. For Terraria, `https://terraria.wiki.gg/api.php?action=parse&page=Eye_of_Cthulhu&prop=sections&format=json` returned valid JSON on 2026-11-07.

Fandom's limits are undocumented and at least one third-party source calls its API inconsistent, so cache pages and send one request at a time.

## Protocol

Pydantic models in `shared/protocol/` are the source of truth, and changes are additive only.

| Direction | Message | Purpose |
|---|---|---|
| Brain to overlay | `subtitle.chunk` | Text in sync with audio |
| Brain to overlay | `avatar.state` | Idle, listening, talking, reacting |
| Brain to overlay | `pointer.fly` / `pointer.hide` | Move the pointer to a target and label it. Optional `target` rect and `ttl_ms` |
| Brain to overlay | `card.show` / `card.update` / `card.close` | Info cards. Optional `page_url` shows a real site, with `body` as its fallback |
| Brain to overlay | `toast.memory` | "Memory updated" notice |
| Brain to overlay | `question.ask` | Clarifying question from the AI |
| Brain to overlay | `settings.state` | Current settings |
| Overlay to brain | `overlay.ready` | Overlay connected, with display scale |
| Overlay to brain | `overlay.rects` | Current element rectangles, for masking |
| Overlay to brain | `card.closed` | Player closed a card |
| Overlay to brain | `card.navigated` | The wiki window's page changed. The URL and title are untrusted data |
| Overlay to brain | `question.answer` | Answer given through the UI |
| Overlay to brain | `settings.update` | Player changed a setting |

## Research notes still to confirm

- How Desktop Duplication and OBS treat Electron's transparent window on the demo machine
- Deepgram Flux's quoted end-of-turn time of about 260 ms, which comes from the original notes and wasn't independently verified
- Whether RapidOCR reads Terraria's font reliably
