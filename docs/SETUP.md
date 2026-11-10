# Setup and usage

[Back to Purrtner](../README.md)

Detailed installation, configuration, memory management, replay and troubleshooting instructions.

## Requirements

- Windows 10 or 11 (macOS works, with the notes under [Troubleshooting](#troubleshooting))
- Python 3.12
- Node.js 24 and npm
- Headphones, so the partner's voice doesn't trigger its own microphone
- API keys for the features you want (see [API keys](#api-keys)). With no keys at all you can still run the overlay demo and replays.

## Setup

From the repo root, in PowerShell:

```powershell
# Python side
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Overlay side
npm --prefix overlay install

# Keys
Copy-Item .env.example .env
```

Then open `.env` and fill in the keys you have. On macOS, activate the venv with `source .venv/bin/activate` and copy with `cp .env.example .env`.

## API keys

Each key turns on one part. Leave a key empty and that part is off; the rest still runs.

| Key | What it turns on |
|---|---|
| `ANTHROPIC_API_KEY` | Watching the screen, replies, tools and pointing. **Without it the partner doesn't watch the game.** |
| `GEMINI_API_KEY` | Fallback model for deep reasoning when there's no Anthropic key |
| `DEEPGRAM_API_KEY` | Hearing you (speech to text). Without it, type to the partner instead. |
| `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` | Speaking out loud. Without both, replies show as subtitles only. |
| `EXA_API_KEY` (optional) | Web search when the game's wiki has no answer |

You can also enter keys in the Control Center's **Keys** tab. They're stored encrypted on your machine and take priority over `.env`.

Other settings in `.env`, all optional:

- `GAME_PROCESS`: the game's process name, such as `Terraria`. Leave it unset and the brain uses the first game window you switch to, and remembers it in `data/games.json`.
- `GAME_TITLE`: the name that memory and the wiki search are filed under. Leave it unset and the partner names the game itself.
- `VOICE_OPTIONS`: voices to offer in settings, as `[{"name":"Rachel","id":"<elevenlabs-voice-id>"}]`.
- `VOICE_HALF_DUPLEX=true`: if you have no headphones. It mutes the mic while the partner talks, so you can't interrupt it.
- `STT_KEYTERMS`, `MIC_DEVICE_INDEX`, `SPEAKER_DEVICE_INDEX`: voice tuning.

## Run it

### With the Control Center (recommended)

```powershell
npm --prefix overlay run dev
```

This opens the overlay and the Control Center. In the Control Center:

1. **Keys**: check that the keys you expect show as set.
2. **Agent**: choose Live, and optionally set the game title, personality and voice.
3. Press **Start partner**.
4. Switch to the game. The partner picks up the first game window you switch to.

The **Console** tab shows the brain's log and the exact command it ran. **Memory** shows what the partner remembers. Closing the Control Center stops everything.

### Manage memory without spending API tokens

Open the dashboard with `npm.cmd --prefix overlay run dev` in PowerShell. Leave **Start partner** unclicked to keep the brain off. Using `npm.cmd` also avoids PowerShell's script execution policy restriction.

In **Memory**, you can review saved facts, history, questions, session notes and the recall preview without starting the partner. Pick a game from the dropdown; the read-only helper uses no model, microphone or capture.

With the brain stopped, use the **three-dot menu** next to each fact to **Edit** or **Forget** it. Each session note has the same inline menu with **Edit** and **Delete note**; edits keep its session and timestamp, and both operations update search and recall. Deleting a note keeps separately stored facts and conversation records. Use **Add fact** above the list to create a fact. Corrections preserve the old fact's validity window; forgetting closes the fact and rejects the same guess in future. The list shows the newest 200 current facts across all games.

**Add sample data** creates two fictional facts and two notes under **Memory test (sample)** once, so you can test inline editing, forgetting and deletion without mixing them into your real game.

**Clear all memory** requires typing `CLEAR`. It saves a database backup first, then clears all games' facts and history, questions, session notes, conversations/events, rejection records and derived vector indexes. Learned game profiles, dashboard settings and custom instructions are kept. Existing exported files, replay recordings and the backup still contain their original data; they are not used as live memory.

**Custom instructions** are saved separately and apply to the next reply, including when changed during play. Examples: “Avoid spoilers” or “Focus on building.” They do not change source/confidence rules. Stop a brain launched from another terminal there before editing memory.

### From the terminal

Start the overlay as above but don't press Start partner, then run the brain yourself in a second terminal with the venv active:

```powershell
python -m brain --live                 # watch the game, listen and talk
python -m brain --live --type          # also take turns typed in the terminal, e.g. `5: what's that` waits 5 s first
python -m brain --live --verbose       # with debug logs
python -m brain --live --record        # also save the session to sessions/ for replay
python -m brain --live --debug-regions # draw the learned HUD regions over the game
```

Press Ctrl+C to stop. Stopping cleanly lets memory close the session.

### Without a game, mic or keys

To see the overlay's avatar, subtitles, pointer, cards and memory toasts with nothing else set up:

```powershell
python scripts/overlay_demo.py         # terminal 1, venv active
npm --prefix overlay run dev           # terminal 2
```

### Replay a recorded session

A session saved with `--record` can be fed back through the same pipeline. Recorded lines appear as subtitles only.

```powershell
python -m brain --replay sessions\<session-dir>
python -m brain --replay sessions\<session-dir> --speed 4 --exit-when-done --write-messages run.jsonl
python scripts/compare_replay.py a.jsonl b.jsonl   # compare two runs, ignoring timing and IDs
```

In the Control Center, choose Replay on the Agent tab and point it at the session folder.

## Before playing Terraria

- Run the game in **windowed or borderless** mode, not exclusive fullscreen, or the overlay can't draw over it. Set it from the main menu, or with the game closed set `"Fullscreen": false`, `"WindowMaximized": true` and `"WindowBorderless": true` in Terraria's `config.json`.
- **Turn off the Steam overlay.** It draws inside the game window, so friend lists and chats could end up in frames sent to the AI.
- To record a demo, use **OBS Display Capture**. Game Capture and Window Capture usually miss the overlay.

## Tests and checks

None of these need a game, a microphone or paid API calls.

```powershell
pytest brain/tests
ruff check --fix brain; ruff format brain
npm --prefix overlay test
npm --prefix overlay run typecheck
```

After changing anything in `shared/protocol/`, regenerate the overlay's types with the venv active:

```powershell
npm --prefix overlay run gen:protocol
```

## Measuring latency

```powershell
python -m brain --live --record 2>&1 | Tee-Object run.log
python scripts/latency_report.py run.log   # p50/p95/max per latency kind
```

The Control Center's **Latency** tab shows the same numbers live.

## Troubleshooting

- **`Cannot find module 'electron'`**: a shell started from VS Code may have `ELECTRON_RUN_AS_NODE=1` set. Clear it with `Remove-Item Env:ELECTRON_RUN_AS_NODE`, then run `npm --prefix overlay run dev` again.
- **A dxcam `COMError` traceback in the log, then "falling back to mss"**: expected on some GPUs. Capture still works through mss.
- **The partner never comments on the game**: check `ANTHROPIC_API_KEY` is set, and that the game window is in front. Capture only runs while the game is focused.
- **The partner talks over itself or interrupts its own lines**: use headphones, or set `VOICE_HALF_DUPLEX=true`.
- **Memory tab shows 0 facts**: memory is filed by game title, so the running brain must use the same title the facts were saved under.
- **macOS shows only the wallpaper**: give your terminal Screen Recording permission in System Settings. Run the game windowed, not in native fullscreen, or the overlay won't appear on its Space.
