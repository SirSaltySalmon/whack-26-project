---
name: run-whack-26-project
description: Build, run, and drive the AI Gamer Partner app (Electron overlay, Control Center window and Python brain). Use when asked to start or launch the app or the partner, open the Control Center, start or stop the brain, take a screenshot of the UI, type a turn to the partner, check what memory holds, run its tests, or interact with the running app.
---

The app is an Electron overlay plus a **Control Center** window that starts and stops the Python brain. Drive it with `.claude/skills/run-whack-26-project/driver.mjs`: one command per call, over the Chrome DevTools Protocol, using only Node built-ins. All paths are relative to the repo root.

Verified on Windows 11 in Git Bash, with Node 24.14.1 and the repo's Python 3.12 `.venv`. It runs on the real desktop: the overlay covers the screen (transparent and click-through) and the Control Center opens as a normal window. Not tried on Linux.

## Setup

Needs the `.venv` from CLAUDE.md. Then:

```bash
source .venv/Scripts/activate
pip install -q -r requirements-dev.txt
npm --prefix overlay install
```

## Build

The driver launches the built app, not the dev server:

```bash
npm --prefix overlay run build
```

## Run (agent path)

```bash
D=.claude/skills/run-whack-26-project/driver.mjs
node $D launch                                  # starts Electron with a debug port, waits for the Control Center
node $D ss 01-agent                             # screenshot -> %TEMP%\partner-shots\01-agent.png
node $D tab Agent                               # always open a tab before acting in it
node $D field "Game title" "Control Center Test"
node $D start                                   # Start partner; waits for "Running" (about 5 s)
node $D state                                   # run state and which capabilities are on
node $D turn "my favourite weapon is the Night's Edge"
node $D logs 4                                  # the brain's last log lines
```

Screenshots and `electron.log` land in `%TEMP%\partner-shots\` (override with `SCREENSHOT_DIR`). Read the PNG to see it.

| command | what it does |
|---|---|
| `launch` / `quit` | start the built app on CDP port 9223 (`CDP_PORT`) / close it, stopping the brain |
| `start` / `stop` / `state` | press Start partner or Stop and wait / print run state and capabilities |
| `tab <title>` | open a sidebar tab: Agent, Keys, Memory, Voices, Console |
| `field <label> <value>` | fill a labelled text field on the open tab |
| `fill <css> <value>` / `submit <css>` | fill any input / submit the form it's in |
| `click <text>` / `click-css <css>` | click a button, label or summary by text / by selector |
| `turn <text>` | a typed player turn (needs Typed turns, on by default) |
| `logs [n]` / `text [css]` / `eval <js>` | brain log lines / page text / any JS in the Control Center |
| `wait <css>` | wait up to 10 s for an element, e.g. after `tab` or a search |
| `ss [name] [overlay]` | screenshot the Control Center, or the overlay window |
| `pages` | list the app's pages |

### Memory with no API keys

With no keys nothing gets remembered, so seed the test title, then look:

```bash
source .venv/Scripts/activate
python .claude/skills/run-whack-26-project/seed_memory.py
node $D tab Memory
node $D click History                           # toggles: a second click turns it off
node $D wait .mem-stats
node $D text .mem-stats
node $D ss 02-memory
```

The tab works with the partner off (it reads memory through `python -m brain --memory`) and opens on the game being played, or the one played last. Pick another with the game picker, a `<select class="mem-game">`. `fill` doesn't drive a select, so use `eval` with the native value setter and a bubbling `change` event.

### Finish

```bash
node $D tab Agent && node $D field "Game title" ""   # the title persists, so clear the test one
node $D stop                                    # clean shutdown: memory closes the session
node $D quit                                    # closes the window, which also stops a running brain
```

### The brain on its own

```bash
python -m brain --describe                      # JSON the Control Center reads: personalities, voices, keys set
```

Start partner runs `.venv\Scripts\python.exe -m brain --live --type`, plus `--record` or `--replay` as set in the Agent tab. The Console tab shows the exact command.

## Run (human path)

`npm --prefix overlay run dev` opens both windows with hot reload. Press Start partner in the Control Center. Closing it quits everything.

## Test

```bash
python -m pytest brain/tests -q                 # 979 passed
npm --prefix overlay test                       # 73 pass
npm --prefix overlay run typecheck
```

## Gotchas

- **`start` uses whatever keys `.env` has.** With keys there, it opens the microphone, sends typed turns to Gemini, watches the screen with paid Haiku once `GAME_PROCESS` is set, and generates barks with ElevenLabs. Check `node $D state` before typing turns. For a key-free run, move `.env` aside first.
- **It's your real desktop.** Someone clicking the window between driver calls changes the open tab. Run `tab X` before `field`, `click` or `text`.
- **The window reopens on the last tab used** (localStorage). Forget `tab Agent` and `field "Game title"` returns `NOT_FOUND`.
- **Choices persist** in `%APPDATA%\overlay\launcher.json`, game title included, and saved keys go in `keys.json`, encrypted with DPAPI. That's why Finish clears the test title.
- **React inputs ignore `.value =`.** `field` and `fill` use the native setter plus an `input` event; plain DOM assignment does nothing.
- **Memory is filed by game title.** A brain started with an empty title files under "Unknown game". The Memory tab's game picker shows any title in memory.
- **Console lines exist in the DOM only while the Console tab is open.** `logs` reads the brain's log through the window's bridge instead, from any tab.
- **The brain log shows a dxcam `COMError` traceback** on this machine, then "falling back to mss". That's expected (see CLAUDE.md).
- **`electron.log` shows `safeStorage ... is deprecated` warnings.** They're harmless on Electron 45.
- **Seeding writes to `data/brain.sqlite3`**, which is gitignored, and only under the test title.

## Troubleshooting

- **`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c`, exit code 127**: Node on Windows was forced out with `process.exit()` while a WebSocket or fetch handle was still closing. The driver awaits each socket's close and lets Node exit by itself; do the same in any new CDP script.
- **`text .mem-stats` prints `(not found)`**: the tab hadn't finished its query. Run `wait .mem-stats` first.
- **`NOT_FOUND: Game title`**: the Agent tab isn't open. Run `node $D tab Agent`.
- **Memory shows `0 facts` after seeding**: the picker is on another game. Pick "Control Center Test".
