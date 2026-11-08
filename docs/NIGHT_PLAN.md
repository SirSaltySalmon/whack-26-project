# Night plan: 2026-11-08, before the 07:30 deadline

Two agents work in parallel tonight, each on its own branch and in its own folder, so neither one switches branches under the other. Both branches start from `wp4-wp5-readers`. That branch is pushed, and it holds `main` plus the readers, the learner and tonight's fixes.

| Who | Branch | Folder |
|---|---|---|
| Claude | `claude/night` | `C:\Users\savva\Documents\WHACK2026` |
| Astra (ChatGPT) | `astra/night` | `C:\Users\savva\Documents\WHACK2026-astra` (a git worktree of the same repo) |

## Rules for both
- Read `CLAUDE.md` first. Its rules hold, especially: no file over 300 lines, never block the asyncio loop, no game-specific logic in `brain/`, and tests that need no game, mic or paid API call.
- **Python:** there is no separate venv in the worktree. Use the main one from inside your own folder: `..\WHACK2026\.venv\Scripts\python.exe -m pytest brain/tests -q`. The brain is imported from the current folder, so this tests your own copy.
- **Before every commit:** run `ruff check --fix brain scripts`, `ruff format brain scripts`, and the full test suite. Commit small, focused changes with messages that say why.
- **Pushing:** push only your own branch. Never push to `main` or `wp4-wp5-readers`; the team merges in the morning.
- **Shared files:** stay inside the files your tasks name. If you must touch a file on the other list, keep the change small and say so in the commit message.

## Astra's tasks (`astra/night`), in this order

### A1. Latency report: new `scripts/latency_report.py`
- **What it reads:** a saved brain log. Each latency line looks like `02:44:05 Latency: event to bark 0 ms (danger_started)`, `Latency: end of turn to first audio 797 ms` or `Latency: player turn took 641 ms`. Lines can be wrapped or interleaved with other output, so match leniently and skip anything that doesn't parse.
- **What it prints:** a Markdown table with one row per latency kind: count, p50, p95 and max in ms. "event to bark" is also split by the event name in brackets.
- **Usage:** `python scripts/latency_report.py run.log`
- **Done when:** `brain/tests/test_latency_report.py` covers parsing, percentiles, wrapped lines and junk lines, all on inline sample text.

### A2. Loop-stall watch: new `brain/loop_watch.py`
- **How it works:** an async task that sleeps 50 ms in a loop and measures how late it wakes. It logs a warning for any stall over 100 ms, with the length, and at exit logs `Event loop: longest stall N ms`.
- **Wiring:** start it in `brain/app.py` next to the other tasks, as `tasks.create_task(survive("Loop watch", watch_loop()))`. That's a one-line change in a shared file, so say so in the commit message.
- **Done when:** a test blocks the loop with `time.sleep(0.2)` inside a coroutine and checks that the stall is reported, using an injectable clock or a short threshold. The test must take under 2 seconds.

### A3. Pointer check script: rewrite `scripts/check_pointing.py`
Pointing now asks for pixel boxes: `[x_min, y_min, x_max, y_max]` in pixels of an image of at most 1280 px. `brain/agent/schemas.py` holds `POINT_PROMPT` and `PointReply`, and `brain/perception/coords.py` holds `pixel_box_to_normalized`. The script still uses the old Gemini 0-1000 `PointTarget`.
- Rebuild it on the brain's own prompt, reply model and conversion.
- Make it take labelled points from a JSON file: `[{"image": "...", "target": "the trash slot", "point": [x, y]}]`, with `point` in full-screen pixels.
- Print the hit rate: how often the labelled point falls inside the returned box.
- Pure helpers, such as hit testing and loading the labels, get unit tests. The script itself makes paid calls, so it's never run in `pytest`.

### A4. Review round 3
Review `brain/learner/regions.py`, `brain/learner/validate.py` and `brain/perception/coords.py` in `git diff origin/main...astra/night`. Focus on the pixel-box conversion, the fill-colour hue ranges, `_counts_as` and `_majority_kind`, and `calibrate`. Report concrete inputs that give a wrong answer, in the same format as rounds 1 and 2. Write them to `docs/reviews/astra-round3.md` on your branch and change no code.

## Claude's tasks (`claude/night`), in this order

### C1. Find mana, and other small HUD elements
In the last live run Haiku reported health in 3 of 3 frames but mana in none. Mana is a single small star at the top right.
- Make the region prompt in `brain/learner/regions.py` ask for every resource display, including single icons.
- Trial prompt changes on saved frames with a Haiku subagent before any paid call.
- **Done when:** the learner pipeline, run on the saved frames, keeps both health and energy.

### C2. Rewind (WP10): a `look_back` tool in `brain/agent/`
Answers "what just hit me?" from the ring buffer's last 10 seconds, on player turns only. The spec is under WP10 in `REMAINING_WORK.md`.

### C3. Latency from the frame (WP9)
Add `frame_ts` to `GameEvent` and set it from the observer's tracker and the readers. Then log `Latency: frame to bark` alongside the existing lines, so A1's report can show it. The spec is under WP9.

### C4. The talker reading its reasoning aloud
In a live run the advice line began "The player's on the character select screen, so there's no progress to build on yet. A tip…". Make advice prompts return only the spoken line, and test that.

### C5. Keep `claude/night` current
Merge `main` in when the team pushes, and keep the whole suite green.

## For the morning (needs the player and the game)
- A live run with mana, then re-export `fixtures/profiles/terraria.json`
- Health falling below 25% fires `health_low` from the reader within about a second
- Relearning after a window resize
- dxcam versus mss on the demo machine, and OBS Display Capture recording the overlay
- A recorded replay session as the stage fallback
- New ElevenLabs credits or key, because the partner is subtitles-only until then
- Merging `wp4-wp5-readers`, `claude/night` and `astra/night` into `main` with the team
