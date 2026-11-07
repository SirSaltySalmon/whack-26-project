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

- **"Not now" tells the brain nothing.** It only closes the question on screen. A question that's been asked is never asked again, so a dismissed one stays open until a session note settles it. Decide if that's right. Fixing it needs a new protocol message.
- **A skipped reaction still uses up its budget.** `decide` runs before the speech slot is checked, so a reaction skipped because the partner is busy still starts the cooldown, and a skipped question still starts the question gap. It's harmless at these values, but it could look like a missed reaction when tuning.
- **The wiki opens behind a cookie dialog.** The window's session is in memory, so wiki.gg should ask again on every launch. Dismiss it before recording a demo.

## 1. Automated tests

All of these need no game, mic or paid calls. Everything the test plan listed is written, apart from WP8's tests below.

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

Overlay logic is tested beside its code, in `overlay/src/renderer/logic/*.test.ts`. Shared helpers are `fakes.py`, `director_rig.py`, `agent_rig.py` and `fake_gemini.py`.

### Still to write, with WP8

**`brain/tests/test_open_page.py`** (new)
- `PlayerStartedSpeaking` sends `page.read` only when the page's hostname exactly matches the wiki's. `wiki.gg.example.com` must not match `wiki.gg`
- A reply with an old `request_id`, or from a different host, is discarded
- Navigating away drops the snapshot, and closing the card forgets the page
- Matching: finds passages by word and prefix, prefers visible ones on a tie, stays under the cap and keeps page order
- A transcript with no overlap sends nothing, and one that refers to the page sends the visible text
- `read_open_page` gives the right text for each case: on the wiki, off the wiki, nothing open
- Page text is never written to SQLite

**`brain/tests/test_director.py`** (add)
- The excerpt reaches player turns and never reaches `_talk`

## 2. Test tooling

**Typed turns: `python -m brain --live --type`.** Each typed line becomes `PlayerStartedSpeaking` and then `PlayerSpeech`, the same events real voice sends, so turns can be tested with no mic or Deepgram key. A prefix like `5: what's that` waits 5 seconds first, so there's time to switch back to the game. Capture stops while the terminal is in front, and `look_closer` says it can't see once capture has been stopped for longer than `look_max_frame_age_s`.

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
- [ ] Once WP8 is built, with a wiki page open: a question it answers past the intro is answered in one Flash-Lite call, with no filler line
- [ ] Once WP8 is built: "what does this say?" uses the part in view, including after scrolling and while minimized
- [ ] Once WP8 is built: follow a link off the wiki, and the partner says it can't read that page. The log shows no read was requested
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
- [ ] Interrupting during a tool call drops the reply, and a card already shown stays up
- [ ] `End of turn to first audio` is under 1 s for a plain reply. If not, stream by sentence and compare TTS models
- [ ] Switching voice in settings changes the next line, and survives a restart (needs `VOICE_OPTIONS`)
- [ ] A quiet stretch brings up a question. Answering by button or out loud shows a memory toast, and it doesn't ask during danger

### Stage 3: add `ANTHROPIC_API_KEY`, Terraria in borderless mode
This also clears the items still unproven in `CLAUDE.md`.
- [ ] Capture works on the demo machine. **dxcam fails on the main dev machine** with `COMError -2005270524` (feature level not supported), so check whether mss keeps up or whether another GPU or session fixes it
- [ ] The overlay draws over Terraria, and OBS Display Capture records it
- [ ] Frames contain only the game, and our own UI is masked (save one with `scripts/save_screenshots.py`)
- [ ] A fight raises an observer event, then a reaction, with hints on or off
- [ ] With hints off, about 10 reactions and questions stay free of tips and of anything not yet found. This depends on the model following its prompt, so read them
- [ ] Pointer accuracy on HUD and on moving world targets, with `pointer_ttl_ms` tuned
- [ ] Terraria's pixel font reads well in an enlarged `look_closer` crop
- [ ] A 30-minute session: no drift in replies, cost near the estimate, and notes appear in the vault

## Known gaps these tests won't close

These are out of scope for the wiring pass:
- **Must-have 3:** learned regions and compiled readers don't exist, so confirmed events stay about 2.4 s old
- **Replay:** `--replay` has no recorder or frame source, so it's neither a test harness nor a stage fallback yet
- **Game brief:** nothing writes it yet, so the talker's context has no game description
- **Barks:** filler lines go through TTS instead of pre-generated audio, so the 300 ms bark budget isn't met yet
