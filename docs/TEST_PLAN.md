# Test Plan

How to test the wiring on the `wiring` branch. The automated tests and test tools are done. **The live checks below haven't been carried out over a game,** because Terraria isn't available.

## What has been checked so far

Checked on 2026-11-07, with no keys or game:

| Check | Result |
|---|---|
| `pytest brain/tests` | 851 pass, the same on repeat runs. A run that blocked every non-loopback connection passed too |
| `npm --prefix overlay test` and `typecheck` | 58 pass, types clean |
| `npm --prefix overlay run build` and `ruff check brain` | Builds, clean |
| Mutation checks on the new tests, on private copies | Director 63 of 63, agent 63 of 64 (the survivor changes nothing today), overlay demo 14 of 14, and 18 of 18 on the WP0 contract, the bug fixes and typed turns |
| Stage 0, with the real brain and the built overlay rendered offscreen and driven by a script | Everything that doesn't need a mouse or a visible window passes. See [Stage 0](#stage-0-no-keys) |

**Not checked:** any real model call, real audio, the overlay in a visible window, or anything over a game. Nothing has confirmed that Gemini accepts our tool declarations or that Flash-Lite picks tools sensibly.

### Bugs this turned up, all fixed

| Bug | Effect | Fix |
|---|---|---|
| A subtitle that arrived already finished never showed | **In subtitles-only mode no line was ever visible,** and WP6's barks would have had the same problem | `companion.css` fades with an animation, because a transition doesn't run on an element's first render |
| The settings panel couldn't scroll | With voices configured, the Voice row was cut off and couldn't be clicked | The panel scrolls, and opens tall enough to show every row |
| A question beside a small character at the top of the screen | Its top ran off the screen | `questionPlacement` keeps room above it. The 160 px is estimated from the CSS, so check it on screen |
| No words from the model after tools ran | The partner went silent after doing the work | `run_turn` returns `after_tools_line` |
| A NaN coordinate from a vision model | It passed the range check and reached the pointer | `NormalizedBox` rejects it |
| An empty final subtitle chunk | Left a trailing space on the line | `joinWords` |

### Found, and left for the team

- **Questions are spoken now.** The popup and its "Not now" button are gone (decision of 2026-11-08). An unanswered question is dropped, and it is not asked again.
- **A skipped reaction still uses up its budget.** `decide` runs before the speech slot is checked, so a reaction skipped because the partner is busy still starts the cooldown, and a skipped question still starts the question gap. It's harmless at these values, but it could look like a missed reaction when tuning.
- **The wiki opens behind a cookie dialog.** The window's session is in memory, so wiki.gg should ask again on every launch. Dismiss it before recording a demo.
- **`Latency: event to bark` leaves out the time spent noticing.** It starts when the event is published, not when its frame was captured, so observer events look seconds faster than they are. It also stops at queuing, not playback. **Fixed by [WP9](REMAINING_WORK.md#wp9-frame-to-voice-latency):** `frame to bark` and `frame to first audio` now count from the frame. The old line stays for comparison.

## 1. Automated tests

All of these need no game, mic or paid calls. Everything the test plan listed is written, including WP8.

| Area | Files in `brain/tests/` |
|---|---|
| Director rules | `test_director_rules.py` |
| Director's speech slot, lines and context | `test_director.py`, `test_director_lines.py` |
| Player turns and tools | `test_agent_turn.py`, `test_agent_tools.py`, `test_agent_knowledge_tools.py`, `test_agent_registry.py` |
| Coordinates, masking, closeups | `test_coords.py`, `test_masking.py`, `test_closeup.py` |
| Gemini tool turns, with no network | `test_gemini_tool_chat.py`, `test_gemini_client.py` |
| Overlay link | `test_server.py` |
| Shared contract | `test_profile_schema.py`, `test_personalities.py` |
| Voice | `test_voice.py`, `test_voice_processors.py` |
| Test tools | `test_typed.py`, `test_overlay_demo.py` |
| Recorder and replay (WP3) | `test_replay_format.py`, `test_recorder.py`, `test_replay.py`, `test_scripted_talker.py`, `test_replay_compare.py`, and `test_replay_app.py`, which records a live run through the real wiring and replays it twice |

Overlay logic is tested beside its code, in `overlay/src/renderer/logic/*.test.ts`. Shared helpers are `fakes.py`, `director_rig.py`, `agent_rig.py`, `fake_gemini.py` and `replay_rig.py`, which writes small sessions to disk.

### Written with WP8

`brain/tests/test_open_page.py` and `test_the_open_page_excerpt_reaches_player_turns_and_never_reactions` in `test_director.py`. The Stage 1 checks against a real wiki page are still open.

## 2. Test tooling

**Typed turns: `python -m brain --live --type`.** Each typed line becomes `PlayerStartedSpeaking` and then `PlayerSpeech`, the same events real voice sends, so turns can be tested with no mic or Deepgram key. A prefix like `5: what's that` waits 5 seconds first, so there's time to switch back to the game. Capture stops while the terminal is in front, and `look_closer` says it can't see once capture has been stopped for longer than `look_max_frame_age_s`.

**Record and replay: `python -m brain --live --record`,** then `python -m brain --replay sessions/<name>`. Recording saves frames, events and every message sent to the overlay under `sessions/`, which is gitignored because it holds screen data. A replay needs no game, mic, keys or network:
- It answers with the recorded lines, speaks in subtitles only, and never opens the mic.
- `--speed 4` plays faster, and `--exit-when-done` stops at the end.
- `--write-messages run.jsonl` saves what it sent, so `python scripts/compare_replay.py a.jsonl b.jsonl` can compare two runs, ignoring timing, IDs and positions.
- A recording's own `messages.jsonl` can be compared with a replay's.

Replay doesn't show the game, so the overlay draws over whatever is on screen. Use it to test the brain's behaviour, and the backup OBS recording as the stage fallback for the game.

**Overlay demo: `python scripts/overlay_demo.py`,** then `npm --prefix overlay run dev` in another terminal. Each pass shows the avatar's states, the pointer, subtitles both ways, a toast for each source, and a question with and without options. Clicking an answer moves on, and otherwise a question holds for 31 s. The terminal logs what the overlay reports back, including the rectangles to mask. The settings panel gets the real personalities, and two fake voices if `VOICE_OPTIONS` isn't set.

## 3. Live checks

Run these in order. Each stage needs more keys. Stages 1 to 3 make paid or quota-limited calls. Tick results in `CLAUDE.md`.

### Stage 0: no keys
Run `python -m brain --live --type` and `npm --prefix overlay run dev`.

Ticked items passed with the real brain and the built overlay, rendered offscreen and driven by a script. Repeat them once in a visible window, because a transparency or click-through problem wouldn't show offscreen. The unticked ones need a person with a mouse.

- [x] Subtitle shows "Brain connected." once, then fades
- [x] Reloading the overlay doesn't greet again
- [x] The gear on the character opens settings, and clicking options updates them
- [x] Settings survive restarting the brain
- [x] A typed line reaches the brain. With no Gemini key it logs `No talker LLM configured`
- [x] Demo script: toast, question and subtitles look right, and their rectangles reach the brain's log
- [ ] The game still gets clicks everywhere except on buttons and card frames
- [ ] The overlay never takes keyboard focus while settings or a question is open
- [ ] At 150% Windows scaling, cards and masks still line up

### Stage 1: `GEMINI_API_KEY`, `GAME_PROCESS`, `GAME_TITLE`
Any windowed game or app works for most of this. First read the real free-tier limits from AI Studio into `rpm_by_model`.
- [ ] "hi" gets a plain reply with no tool call and no filler. This also proves Gemini accepts the tool declarations
- [ ] "look up the Eye of Cthulhu" shows a card, with a filler line first
- [ ] WP8 is built. With a wiki page open: a question it answers past the intro is answered in one Flash-Lite call, with no filler line
- [ ] "what does this say?" uses the part in view, including after scrolling and while minimized
- [ ] Follow a link off the wiki, and the partner says it can't read that page. The log shows no read was requested
- [ ] "open the wiki page for slimes" opens the real site in the wiki window
- [ ] "what am I holding?" uses `look_closer`, and the answer matches the screen
- [ ] "point at my health" lands the pointer beside the target, at 100% and 150% scaling
- [ ] "something it can't see" gets "I can't find it", not a guess
- [ ] Tool follow-ups don't fail on thought signatures
- [ ] Over the limit (lower `rpm_by_model` to force it): a canned line and a log, not silence
- [ ] Flash-Lite picks tools sensibly over about 20 varied requests. If not, try another `talker_model`
- [ ] Note the `Latency: player turn took` log line for a plain reply and for a tool reply

### Stage 2: add `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
Use headphones.
- [ ] Spoken turn, end to end
- [ ] Subtitles arrive in step with the audio
- [ ] Interrupting mid-sentence stops the audio and ends the subtitle
- [ ] Interrupting a plain reply drops it. Talking during `look_closer` doesn't: the answer comes once you stop, and a card already shown stays up
- [ ] `End of turn to first audio` is under 1 s for a plain reply. If not, stream by sentence and compare TTS models
- [ ] A reaction the talker says logs `Latency: frame to first audio`, and a bark logs both `frame to bark` and `frame to first audio`. Talking over a reaction before it plays logs neither, and the Control Center's Latency tab shows the same numbers as the log
- [ ] Switching voice in settings changes the next line, and survives a restart (needs `VOICE_OPTIONS`)
- [ ] A quiet stretch speaks a question. Answering out loud or in the text box shows a memory toast, and it doesn't ask during danger

### Stage 3: add `ANTHROPIC_API_KEY`, Terraria in borderless mode
This also clears the items still unproven in `CLAUDE.md`.
- [ ] Capture works on the demo machine. **dxcam fails on the main dev machine** with `COMError -2005270524` (feature level not supported), so check whether mss keeps up or whether another GPU or session fixes it
- [ ] The overlay draws over Terraria, and OBS Display Capture records it
- [ ] Frames contain only the game, and our own UI is masked (save one with `scripts/save_screenshots.py`)
- [ ] A fight raises an observer event, then a reaction, with hints on or off
- [ ] Focus: calm play logs reports about every 1.3 s. A fight logs `Watching the game at medium focus` (or high), and `low` again about 5 s after it ends
- [ ] "Watch this" before something exciting calls `watch_closely` with no filler line, and a plain chat turn never calls it. It isn't called again while a boost runs
- [ ] After a boost ends, the partner doesn't remark on it
- [ ] With hints off, about 10 reactions and questions stay free of tips and of anything not yet found. This depends on the model following its prompt, so read them
- [ ] Pointer accuracy on HUD and on moving world targets, with `pointer_ttl_ms` tuned
- [ ] Terraria's pixel font reads well in an enlarged `look_closer` crop
- [ ] Learning: with `GAME_TITLE` set and no profile, the log shows `Learning where the HUD is`, then `Reader health (...) kept` or `rejected` with a reason, and a "Learned where your ..." toast. It makes at most 6 Gemini calls
- [ ] With `--debug-regions`, boxes sit on the HUD elements, turn grey under a card dragged over them, and show values that follow the game
- [ ] Taking damage below 25% logs `Reader health: health_low` and the reaction comes within about a second. The observer doesn't raise a second `health_low`
- [ ] Resizing the game window logs `Readers paused` and a relearn follows
- [ ] `scripts/export_profile.py` saves a fixture, and `PROFILE_FIXTURE` loads it on a fresh database with a `SEEDED profile` warning
- [ ] A 30-minute session: no drift in replies, cost near the estimate, and notes appear in the vault
- [ ] Record a few minutes with `--record`. The log's MB/s at the end is near the 1-2 MB/s estimate, and `dropped_frames` in `manifest.json` stays at 0
- [ ] Replay that session twice with `--exit-when-done --write-messages`. `compare_replay.py` finds no difference between the two runs, or between either run and the recording's `messages.jsonl`
- [ ] Replay with the overlay open: recorded pointers and cards appear, and subtitles show the recorded lines

## 4. Benchmarks

The numbers for the pitch, measured with [WP11](REMAINING_WORK.md#wp11-proof-benchmarks-and-evals)'s tools. Save the log of every live run with `python -m brain --live --record 2>&1 | Tee-Object run.log`, then run `python scripts/latency_report.py run.log`. Fill in a row each time you measure, with the date and the run's name.

| Measure | Target | Result | Run |
|---|---|---|---|
| Frame to bark, reader events (WP9) | Under 1 s (starting target) | | |
| Frame to first audio, observer events (WP9) | Report only. This is the slow path readers replace | | |
| Event to bark | Under 300 ms (`CLAUDE.md`) | | |
| End of turn to first audio | Under 1 s (`CLAUDE.md`) | | |
| Player turn with a tool | Report only | | |
| Longest event-loop stall in 30 minutes | Under 100 ms (starting target) | | |
| Reader replay: two runs give the same messages | No difference | | |
| Observer: precision and recall for elevated danger | Report only | | |
| Two-frame filter: false alarms on calm scenes | `tracker.py` measured 2 of 160 | | |
| Tool choice over about 20 requests | Report only | | |
| Pointer hit rate | Report only | | |

## Known gaps these tests won't close

- **Must-have 3:** learned regions and compiled readers are on `origin/wp4-wp5-readers`, not on `main`. Until that merges, confirmed events stay about 2.4 s old.
- **Barks** are pre-generated, and the 300 ms budget is not measured yet. [WP9](REMAINING_WORK.md#wp9-frame-to-voice-latency) now logs it from the frame, so a live run can.
- **Frame to first audio isn't logged in subtitles-only mode,** including replays, because there's no audio to time. `frame to bark` is still logged there, when it's queued.
- **The game brief** is written on `main`. It still needs a check on a few real games.
