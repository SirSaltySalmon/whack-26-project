# Architecture

The system runs as two processes joined by a localhost WebSocket: a **Python brain** and an **Electron overlay**.

Python owns capture, computer vision, voice, memory and the agent loops, because Pipecat, OpenCV, the OCR tools and the vision SDKs all live there. Electron owns everything the player sees, because it's a reliable way to draw a transparent, click-through overlay on top of a game.

Vendor details were checked on 2026-11-07. Re-measure latency on the demo machine rather than trusting these figures.

`docs/original ideation.md` and `docs/original tech stack.md` are the first notes, kept for history. Where they differ from this page, this page is current, and the [decision log](DECISIONS.md) says why.

## Data flow

```
dxcam ─► ring buffer (full-res, 10s) ─┬─► mask overlay rects ─► downscale ─► HAIKU OBSERVER (every 0.8 s) ─► tracker (agreeing frames only) ─┬─► live state in RAM
                                      │                                                                                                      └─► EVENT BUS
                                      ├─► (not built) scene match ─► compiled readers (OCR/colour) ─► EVENT BUS
                                      └─► player turns only: masked full-res crop ─► TOOLS
mic ─► Pipecat (Deepgram Flux) ─► transcript / barge-in ─► EVENT BUS

EVENT BUS ─► DIRECTOR (rules: budgets, cooldowns, priorities, one speech slot)
               ├─► PLAYER TURN: Flash-Lite with TOOLS ─► TTS (subtitles in step with audio)
               │     TOOLS: look closer, point (Gemini vision) · wiki · note a question · think hard (deep model)
               ├─► EVENT REACTION: Flash-Lite, no tools ─► TTS
               ├─► QUESTION: next open question from memory ─► TTS and overlay
               └─► (not built) REFLEX: cached bark ─► TTS
SLOW LOOP: session notes (deep model); (not built) learning regions and the game brief

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
| **Screen awareness** | `claude-haiku-5-5` on the newest frame every 0.8 s, reports count only once frames agree | Works in any game with nothing learned first. A confirmed report is about 2.4 s old. See the [decision log](DECISIONS.md) | Moondream (missed most fights and all health values); Gemini free tier (can't sustain the rate) |
| **Local perception** | OpenCV and numpy for colour readers and frame diffs; `imagehash` for scene matching; RapidOCR. **Not built yet** | Readers compiled from learned regions would give reactions under a second, with no LLM | — |
| **Voice pipeline** | Pipecat with local audio transport | Easy to inject director events, reports per-turn latency. The pipeline holds no LLM: the director calls the talker and passes text to TTS | LiveKit Agents (turn model tied to LiveKit); Gemini Live and OpenAI Realtime (less control over when it speaks) |
| **STT and end of turn** | Deepgram Flux via `DeepgramFluxSTTService` | Transcription and turn detection in one model. `StartOfTurn` drives barge-in, and `enable_eager_end_of_turn` can cut latency | Nova-3 with Smart Turn; Silero on the voice path (Flux doesn't need it) |
| **TTS** | ElevenLabs: benchmark `eleven_flash_v2_5` against `eleven_v4_turbo`. Cartesia Sonic as optional backup | Both list about 100 ms median, excluding network. ElevenLabs recommends v4 Turbo for real-time use; Flash is cheaper. Pre-generate barks per personality at startup | Hume (stretch only) |
| **Talker LLM** | `gemini-3.5-flash-lite` on the free tier; 12-word cap | Stable and free. It also runs player turns and chooses their tools. The reply is collected, then sent to TTS, so the whole reply's time counts toward the 1 s budget and still needs measuring. Small pre-assembled context | Large models on the voice path; paid models beyond the observer (no budget) |
| **Agent tools** | In-process registry in `brain/agent/`, on player turns only | The tools need the brain's in-memory frames, overlay link and database. An MCP adapter can wrap the registry later | Pipecat's `MCPClient` (needs an LLM in the pipeline and keeps only text results); a separate MCP process (can't reach the frames) |
| **On-demand vision** | `gemini-3.6-flash` (stable); try `gemini-3.8-flash` (new) | Answers `look_closer` and `point_at`, and later the profile learner. Low resolution by default, full-resolution crops when the player asks. Structured JSON and pointing coordinates from one provider | Moondream (only if Gemini's coordinates prove too slow) |
| **Deep reasoning** | `gemini-3.6-flash` with higher thinking | Session notes, and `think_hard` on player turns. Later post-mortems and profile cleanup. It shares quota with vision | Larger paid Claude models (no budget) |
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
| **Subtitles** | Bottom center and click-through. Fade after the utterance ends |
| **Memory toast** | Top center and click-through. Shows what was saved and its source, then fades after 4 s |
| **Question** | Beside the character. Only its buttons catch clicks. An open question is answered out loud, and an unanswered one goes away after 30 s |
| **Settings** | Opened with the gear on the character. Hints, personality and voice, using buttons only |

Only lookups the player asked for send `page_url`, so the partner can't change the page while the player is reading it or cover the game mid-fight. Scrolling and clicking links shouldn't take keyboard focus from the game. Typing into a page needs the player to ask for focus, and the game gets no keys until they click back into it.

If a page can't load, the window shows `body` as text, so research still works without a network.

The overlay checks element rectangles about every 100 ms and reports only changes. Capture runs at about 5 fps, so that's frequent enough, and one check covers drags, animations, opening and closing. A fast drag can show briefly past the mask.

Masks are filled with black, so a reader whose region is under an overlay element must report the value as unknown rather than reading the black pixels.

## Player turns and tools

The director starts a player turn in its one speech slot. The model replies directly, which takes one call, or asks for tools. On its first tool call the partner says a short filler line, because results take seconds. A turn makes at most three model calls, and the last has tools turned off so it ends in words.

| Tool | What it does |
|---|---|
| `look_closer` | Asks vision about the frame from when the player **started** speaking. Masks it, crops to a named area (the model can't see the frame, so it can't give coordinates) and enlarges small crops by whole multiples to keep pixel fonts crisp |
| `point_at` | Finds a box on the **newest** frame and sends `pointer.fly` with a short `ttl_ms` |
| `lookup_wiki` | Shows a card. `open_page` opens the real site, and the URL always comes from the wiki client, never the model |
| `note_unknown` | Opens a question for later instead of guessing |
| `think_hard` | Asks the deep model, shows the full answer in a text card and gives the talker a short version to speak |

Tool results reach the model labelled as data. Vision answers are observations and aren't stored as facts. A barge-in cancels the turn, but anything it has already shown stays up.

Questions also go through the director: on a timer, it asks only when the overlay is connected, things have been quiet, enough time has passed since the last question, there's no danger and hints are on.

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

The research client takes any MediaWiki `api.php` base URL, so it isn't tied to Fandom. `brain/research/discovery.py` finds the wiki from the game title in this order:

1. A configured override URL.
2. `<slug>.wiki.gg`, then `<slug>.wiki`.
3. Exa, if a key is set. The `api.php` is read from the result page's standard `EditURI` link.
4. `<slug>.fandom.com`, last, because Fandom often hosts unofficial forks.

A candidate counts only if it returns real siteinfo JSON whose name matches the game. Unknown wiki.gg subdomains return a 401 HTML page.

Checked live on 2026-11-07:

- Terraria resolves to terraria.wiki.gg, Minecraft to minecraft.wiki, and Hollow Knight to Fandom.
- Stardew Valley's official wiki is stardewvalleywiki.com, so without Exa it falls back to Fandom.

Lookups fetch only section 0 (`action=parse&section=0`), which is the intro plus the infobox. Exact titles go straight to the page; anything else goes through wiki search with question filler removed. `sanitize.py` turns the HTML into plain text: it reads both `th`/`td` infoboxes and Fandom portable infoboxes. Fetched pages are cached in the `wiki_cache` SQLite table, and cards are rebuilt from them. Try it with `python -m scripts.wiki_lookup Terraria "Eye of Cthulhu"`.

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
| Brain to overlay | `settings.state` | Current settings, plus the personalities and voices on offer |
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
