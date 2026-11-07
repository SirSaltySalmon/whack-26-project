The game-agnostic version runs as two processes: a **Python "brain"** and an **Electron "face"**, joined by a WebSocket. Python owns capture, computer vision, voice, memory and the agent loops, because Pipecat, OpenCV, the OCR tools and the vision SDKs all live in Python. Electron owns everything the player sees, because it's the most reliable way to draw a transparent, click-through overlay on top of a game.

## The stack

| Layer | Pick | Why | Rejected |
|---|---|---|---|
| **Overlay / UI** | Electron + React + Vite; Framer Motion for the pointer; Rive or Lottie for the avatar | `setIgnoreMouseEvents(true, {forward:true})` makes the overlay click-through but still hoverable, so you can switch interaction on when the cursor reaches the info card. Framer Motion handles bezier-arc pointer flights easily | Tauri (no `forward` option, so a closable or resizable card is painful). Requires the game in **borderless or windowed** mode |
| **Brain process** | Python 3.11+, asyncio, FastAPI WebSocket to Electron | Puts voice, computer vision and the LLM SDKs in one language and one event loop | Node backend (weaker CV and voice ecosystem) |
| **Screen capture** | **dxcam** on Windows (fast DXGI capture); **mss** as the cross-platform fallback | Grab at 5–10 fps into a full-resolution ring buffer of about 10 seconds in RAM. Downscale copies for the AI | Electron `desktopCapturer` (frames are stuck in the renderer, so they'd have to be piped to Python) |
| **Local perception** | OpenCV + numpy for colour-bar readers and frame diffs; `imagehash` for perceptual-hash scene matching; **RapidOCR** for local OCR | These run the readers the AI compiles from its learned `regions` at about 10 Hz without any LLM. This is what makes a game-agnostic setup fast enough | Continuous VLM watching (slow, expensive, and the context fills with redundant frames) |
| **Voice pipeline** | **Pipecat** (local audio transport, Silero VAD, interruption handling) | Easy to inject the director's events into the pipeline, and it reports latency for each turn | LiveKit Agents (its turn model is tied to LiveKit). Gemini Live / OpenAI Realtime (no ElevenLabs voices, and less control over when it speaks) |
| **STT + end of turn** | **Deepgram Flux** | Transcription and turn detection in one model, about 260 ms to end of turn. Its start-of-turn signal drives barge-in | Nova-3 + Smart Turn (two parts to wire up) |
| **TTS** | **ElevenLabs Flash v2.5**; **Cartesia Sonic** as a hot-swap backup | Your choice of voice options. Stream it, and send each subtitle chunk to the overlay at the same moment as its audio. Pre-generate a bank of short reaction lines ("barks") for each personality at startup | Hume (put it in the stretch goals, for prosody) |
| **Fast talker LLM** | **Gemini Flash** (latest) or **Claude Haiku 4.5**, streaming, 12-word cap | Low time to first token. It only ever sees a small pre-assembled context | Big models on the voice path |
| **Slow vision + profile learner** | **Gemini Flash** with `media_resolution` | Low-resolution frames (about 280 tokens) by default, then a full-resolution crop from the ring buffer when the player asks or an event fires. It returns structured JSON and screen coordinates for pointing. One provider covers seeing and pointing | Moondream (only if Gemini's coordinates turn out to be too slow) |
| **Deep reasoning** | **Claude Sonnet** | Post-mortems, cleaning up the game profile during downtime, deciding which clarifying questions are worth asking. Latency doesn't matter for these | — |
| **Memory** | **SQLite** in WAL mode + JSON1 + FTS5 + **sqlite-vec**; local embeddings via **fastembed** (bge-small) | Fixed meta-schema with a game profile the AI learns as data, plus a fact graph with confidence and validity windows. WAL lets the fast loops read while the slow loop writes. Local embeddings avoid a network call during recall | Zep, Mem0, Letta (more infrastructure, less control, and nowhere to put your learned regions and readers) |
| **Web research** | **Fandom MediaWiki API** (`action=parse`, found by game title), **Exa** as fallback | Works for any game: at startup, research the title and pre-fill tentative `entity_types`. Prefetch during downtime and show sanitized cards | Perplexity (slow); loading live pages in the overlay |
| **Director / event bus** | Plain Python: asyncio queues + a rules module | Deterministic, instant, testable. The "when to speak" logic shouldn't wait on an LLM | An LLM deciding when to talk |
| **Tilt meter (stretch)** | Mic loudness and pitch via numpy, death streaks from events, profanity hits in transcripts | Cheap, and the change in behaviour is easy for judges to see | Hume in the critical path |
| **Demo safety** | Replay mode that records frames, audio and events to disk and feeds them back through the same pipeline | Your fallback if the network or the game misbehaves on stage | — |
| **Export (optional)** | Markdown post-mortems and session retros into an Obsidian folder | Obsidian is useful for showing off what it remembers, but it shouldn't be the store | Obsidian as the memory itself |

## How the pieces connect

```
dxcam ─► ring buffer (full-res, 10s) ─┬─► downscale ─► perceptual-hash scene match ─► compiled readers (OCR/colour) ─► EVENT BUS
                                      └─► on demand: full-res crop ──────────────────────────────────────────────┐
mic ─► Pipecat (Silero VAD → Deepgram Flux) ─► transcript / barge-in ─► EVENT BUS                                │
                                                                                                                 ▼
EVENT BUS ─► DIRECTOR (budgets, cooldowns, priorities) ─┬─► REFLEX: cached bark → ElevenLabs
                                                        ├─► TALKER: Gemini Flash/Haiku → ElevenLabs Flash (streamed + subtitles)
                                                        └─► SLOW: Gemini Flash vision (learn regions, answer, point) / Claude Sonnet (post-mortems, consolidation)
                                     all read/write ─► SQLite (profile · entities · facts · events · summaries · questions · player)
                                     all render via WebSocket ─► Electron overlay (avatar, pointer, subtitles, cards, "memory updated" toasts)
```

## Why it fits together

- **The fast loops never call a vision model.** Reactions in under a second come from compiled readers and cached barks. The vision model only teaches the system and answers questions, which keeps you game-agnostic without vision latency.
- **Two LLM providers, not five.** Gemini sees and points; Claude thinks deeply. That's fewer keys, rate limits and failure points on demo day. Deepgram and ElevenLabs are the only other paid services.
- **Every piece is swappable behind one interface.** ElevenLabs ↔ Cartesia, Gemini ↔ Haiku. If one vendor has an outage on stage, you change one config line.
- **Splits cleanly across a team:** (1) Electron overlay, (2) capture, perception and compiled readers, (3) Pipecat voice and director, (4) memory, profile learner and post-mortems. They meet at a WebSocket message schema, so agree on that in the first hour.

The model names and versions above are as of the research. Check current versions and pricing, and measure end-to-end latency on your demo machine, in the first hour. Also check two things early on that machine: that dxcam can capture your chosen game, and that the Electron overlay draws over it.