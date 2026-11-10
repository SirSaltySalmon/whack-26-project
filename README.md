<h1 align="center">🐾 Purrtner</h1>

<p align="center">
  <strong>An AI companion that watches your game, talks with you, and remembers your adventure.</strong><br>
  Game-agnostic by design, with no game-specific logic or integrations.
</p>

<p align="center">
  <a href="https://devpost.com/software/purrtner">Devpost submission</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#try-it">Try it</a> ·
  <a href="docs/SETUP.md">Setup guide</a>
</p>

![Purrtner points to a grandfather clock in Terraria, with a cat companion and spoken-response subtitles](docs/images/terraria-clean.png)
## A Gaming Companion

Purrtner sits alongside your game as a small desktop companion. Ask about something on screen, get a pointer to the object, look up a wiki page, or talk through what to do next. It can also speak up about the action and ask questions to learn your goals and preferences.

We built it as a four-person hackathon project around a simple idea: a good gaming companion needs to understand both **what is happening now** and **what matters to this player**.

Our hackathon testing covered **Terraria, Minecraft and Slay the Spire**. Game knowledge and learned HUD layouts are stored as data, so supporting another game does not require writing a game-specific integration. Accuracy depends on what is visible and how well the models interpret it.

| Capability | What the player gets |
| --- | --- |
| **Screen awareness** | Context about the scene, nearby objects and learned HUD readings. |
| **Voice conversation** | Short spoken replies, synchronized subtitles and support for interruptions. |
| **Memory with provenance** | Player preferences and playthrough facts with sources, confidence and correction history. |
| **On-screen pointing** | A pointer that flies to an object instead of leaving you guessing which one it means. |
| **Wiki research** | Relevant pages in a movable, resizable in-game wiki window. |
| **A companion you can tune** | Personalities, voices, avatars, visual themes and adjustable pacing for proactive comments. |


### Watching the live gameplay
The debug view exposes the information behind a response: object boxes, a learned health region, the last voice input, the director's decision and the current attention level. Attention increases during danger and settles back down in quieter moments.

![Scripted Terraria danger scene with zombie outlines, low-health HUD reading, high attention, voice-input debug panel and an escape warning](docs/images/terraria-danger.png)

### Useful answers based on internet sources

A player can ask which enchantment would help against a mob on screen. Purrtner can inspect the scene, point to the target, and open the relevant wiki page.
![Scripted Minecraft interaction identifying a zombie and recommending Smite V, with the real Minecraft Wiki open alongside gameplay](docs/images/minecraft-wiki.png)

### Remembering your playthrough

Memory covers your goals, preferences and progress. Each fact keeps its source: **player**, **observed** or **wiki** along with confidence and a validity window. Player statements take priority; corrections close the previous fact rather than silently erasing it. Uncertain or conflicting information can become a question for the player.

The Control Center lets you inspect facts, edit or forget them, review session notes and see the exact context a reply would receive. Recall supports keyword search and optional local semantic search.

![Purrtner Memory dashboard showing source labels, confidence, a corrected base location and an assembled recall preview](docs/images/dashboard-memory.png)
### Make it your Purrtner

Choose a personality, voice and avatar; switch between hints and conversation; and adjust how often the companion speaks up. Uploads support background removal, and the avatar can be moved and resized over the game.

![Avatar picker with the built-in cat, custom uploads and background-removal controls](docs/images/dashboard-avatars.png)

<details>
<summary><strong>Explore the Control Center</strong></summary>

The desktop dashboard brings together agent settings, pacing, API keys, memory, voices, avatars, latency and logs. You can browse saved memory while the partner is stopped.

![Control Center agent settings, including personality, microphone, memory search and live or recorded-session launch modes](docs/images/dashboard-agent.png)

*Settings and avatar screenshots from our Devpost submission.*

</details>

## How it works

Two local processes share a typed WebSocket contract: a **Python brain** handles perception, conversation and memory, while an **Electron + React overlay** handles everything the player sees.

```mermaid
flowchart LR
    Game[Game window] --> Capture[Capture + masking]
    Capture --> Vision[Perception]
    Mic[Microphone] --> Voice[Speech detection]
    Vision --> Director[Rule-based director]
    Voice --> Director
    Director --> Agent[Conversation + tools]
    Agent <--> Memory[(SQLite memory)]
    Agent <--> Wiki[Wiki research]
    Agent --> Speech[TTS]
    Speech --> Overlay[Overlay]
    Agent --> Overlay
```

### Engineering choices

- **Control when to speak.** A deterministic director applies priorities, cooldowns and speech budgets. The language model generates the response; the director schedules it and handles interruptions.
- **Use attention where it helps.** A rolling frame buffer supports close looks and looking back. Vision reports run at an adaptive cadence, while learned HUD readers can process regions locally. Consecutive observations must agree before a report is accepted.
- **Keep memory useful over time.** SQLite stores facts and Markdown session notes, with FTS5 search and optional local vector recall. Replies receive a small assembled context rather than the entire conversation history.
- **Avoid visual feedback loops.** The overlay reports its element rectangles so capture can mask subtitles, cards and other UI before perception. The pointer sits beside its target to keep the target visible.
- **Make failures reproducible.** Sessions can record frames, events and overlay messages for replay. Shared fakes let automated checks run without a game, microphone or paid API calls.
- **Keep provider choices replaceable.** Model access lives behind one factory with per-model rate limits. Voice, capture and research providers have their own interfaces.

During our demo usage, running costs were roughly **US$0.02 per minute**, and we spent **under £5 during development**. These are approximate figures from our team's use; model, voice and attention settings affect running costs.

| Layer | Technologies |
| --- | --- |
| Desktop interface | Electron, React, TypeScript, Vite, Motion |
| Backend and transport | Python 3.12, asyncio, FastAPI, localhost WebSocket |
| Capture and local perception | DXcam with MSS fallback, OpenCV, NumPy, RapidOCR |
| Models | Anthropic Claude for current vision and conversation roles; Gemini support and fallback roles |
| Voice | Pipecat, Deepgram Flux, ElevenLabs |
| Memory and recall | SQLite WAL, FTS5, optional sqlite-vec and fastembed |
| Research | MediaWiki API, cached pages, optional Exa search |
| Shared contract | Pydantic models with generated TypeScript types |

Model configuration lives in [`brain/config.py`](brain/config.py). The [architecture](docs/ARCHITECTURE.md) and [decision log](docs/DECISIONS.md) explain the design and its evolution.

## Try it

You need **Python 3.12**, **Node.js 24 + npm**, and Windows 10/11. macOS has a capture path with additional permissions and windowing requirements; see the [setup guide](docs/SETUP.md#troubleshooting).

From the repository root, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
npm.cmd --prefix overlay install
Copy-Item .env.example .env
```

**Preview without keys, a game or a microphone:**

```powershell
# Terminal 1, with the virtual environment active
python scripts/overlay_demo.py

# Terminal 2
npm.cmd --prefix overlay run dev
```

The demo scripts the overlay's avatar, subtitles, pointer, cards and memory toasts. It does not run a live AI companion.

**Play with the live companion:** stop the demo server, configure your keys in `.env` or the Control Center, then choose **Live game → Start partner** and switch to a windowed or borderless game.

| Key | Feature |
| --- | --- |
| `ANTHROPIC_API_KEY` | Screen observation and the default conversation/tool models |
| `DEEPGRAM_API_KEY` | Microphone transcription; typed turns are available without it |
| `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` | Spoken output; replies use subtitles without both |
| `GEMINI_API_KEY`, `EXA_API_KEY` | Optional model fallback and search capabilities |

Use headphones for voice interaction. Capture is limited to the focused game window, but live use sends game images and conversation data to the configured cloud providers. Replay recordings remain local and are excluded from Git.

See the [full setup guide](docs/SETUP.md) for memory management, recording, replay, configuration and troubleshooting.

## Development

```powershell
python -m pytest brain/tests
npm.cmd --prefix overlay test
npm.cmd --prefix overlay run typecheck
```

The checks cover director rules, memory authority and conflicts, coordinate conversion, overlay masking, replay and UI behavior. The commands above do not require live services.

| Directory | Responsibility |
| --- | --- |
| [`brain/`](brain/) | Capture, perception, voice, director, memory, research and player-turn tools |
| [`overlay/`](overlay/) | Game overlay and desktop Control Center |
| [`shared/protocol/`](shared/protocol/) | Source of truth for cross-process messages |
| [`scripts/`](scripts/) | Offline demos, diagnostics, recording utilities and showcase rendering |

After changing the protocol, regenerate the TypeScript types with `npm.cmd --prefix overlay run gen:protocol` and the virtual environment active.

## Project notes

Purrtner is a hackathon prototype. Longer playthroughs, more game genres and broader hardware testing are the next steps; long-term reliability over hundreds of hours is still to be evaluated. Highlights and an achievement gallery are future ideas, not current features.

- [Devpost submission](https://devpost.com/software/purrtner)
- [Setup and usage](docs/SETUP.md)
- [Architecture](docs/ARCHITECTURE.md) · [Design decisions](docs/DECISIONS.md)
- [Test plan](docs/TEST_PLAN.md) · [Remaining work](docs/REMAINING_WORK.md)

The furnished Terraria showcase uses [Home Sweet Journey's Rest by TelBuilds](https://www.curseforge.com/terraria/maps/home-sweet-journeys-rest). The Minecraft wiki window displays the [Smite article](https://minecraft.wiki/w/Smite).

## License

[MIT](LICENSE).
