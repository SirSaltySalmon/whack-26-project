# Test Plan

How to test the wiring on the `wiring` branch. **Nothing here has been carried out yet**, because Terraria isn't available.

## What has been checked so far

Checked on 2026-11-07, with no keys, network or game:

| Check | Result |
|---|---|
| `pytest brain/tests` | 396 pass. `test_talker`'s fake voice was updated, because `say()` now returns whether it spoke |
| `npm --prefix overlay test` and `typecheck` | 33 pass, types clean |
| `npm --prefix overlay run build` | Builds |
| A throwaway script with fake models (not in the repo) | 55 checks pass on the tool loop, tools, Gemini message handling and director |
| The real brain with a fake Gemini key, connected to as if by the overlay | Starts, sends personalities and voices, greets, and saves and echoes settings |

**Not checked:** any real model call, real audio, the overlay's new parts on screen, or anything over a game. Nothing has confirmed that Gemini accepts our tool declarations or that Flash-Lite picks tools sensibly.

## 1. Automated tests to write

These need no game, mic or paid calls. `CLAUDE.md` requires tests for the director rules and coordinates, so write those first.

**`brain/tests/test_director_rules.py`**
- `PlayerStartedSpeaking` gives `CancelSpeech`, and the next `PlayerSpeech` carries its `started_at`
- Reconnecting the overlay doesn't greet again
- `Tick` asks only when all of these hold: overlay connected, quiet for `question_quiet_s`, `question_gap_s` since the last question, no danger
- `GameEvent` and `Tick` act the same with hints on or off
- Danger starts and ends with `danger_started`, `danger_high` and `danger_ended`
- `SettingsChanged` gives `SetVoice`

**`brain/tests/test_director.py`** (new)
- Events keep being handled while a player turn is stuck in the model
- Barge-in cancels a turn, and its stale reply is never spoken
- A new player turn replaces one in progress, while event reactions are skipped when the slot is busy
- A failed action doesn't stop the loop
- `on_spoken` isn't called when `say()` returns `False`
- A question is shown and spoken, and `take_question` returning `None` stays quiet

**`brain/tests/test_agent_turn.py`** (new)
- Plain text reply: one model call and no filler
- Tool, then text: exactly one filler line
- Stops at the step cap, with tools turned off on the last call
- Over quota on the first call raises; over quota after a tool returns `after_tools_line`
- The final text keeps to the word cap

**`brain/tests/test_agent_tools.py`** (new)
- `look_closer` uses `RingBuffer.nearest(started_at)`, `point_at` uses the newest frame, and both use high detail
- Overlay rectangles are masked in what's sent, and the buffer's frame stays untouched
- Pointer rectangle at 100% and 150% scale, with a window offset and a cropped area
- A malformed or `found: false` box sends no pointer
- `page_url` is set only when `open_page` is true, and its value comes from the wiki client
- A stale frame gives the "can't see" text
- Tool output is labelled as data
- The registry returns text for an unknown tool, invalid arguments, a timeout, an unavailable LLM and an exception

**`brain/tests/test_closeup.py`** (new)
- Each area gives the right `CropRegion`, including the window offset
- Large crops shrink, and small crops grow by whole multiples

**`brain/tests/test_llm.py`** (add)
- `GeminiToolChat` passes the model's `Content` back unchanged, including `thought_signature`
- Results carry the call's `id` and `name`
- `allow_tools=False` sets mode `NONE`, and automatic function calling is off

**`brain/tests/test_open_page.py`** (new)
- `PlayerStartedSpeaking` sends `page.read` only when the page's hostname exactly matches the wiki's. `wiki.gg.example.com` must not match `wiki.gg`
- A reply with an old `request_id`, or from a different host, is discarded
- Navigating away drops the snapshot, and closing the card forgets the page
- Matching: finds passages by word and prefix, prefers visible ones on a tie, stays under the cap and keeps page order
- A transcript with no overlap sends nothing, and one that refers to the page sends the visible text
- `read_open_page` gives the right text for each case: on the wiki, off the wiki, nothing open
- Page text is never written to SQLite

**`brain/tests/test_director.py`** (add, once WP8 is built)
- The excerpt reaches player turns and never reaches `_talk`

**`brain/tests/test_server.py`** (add)
- `settings.state` includes `personalities` and `voices`

**`overlay/src/renderer/logic/subtitles.test.ts`** (new)
- Word chunks join with spaces, but not before punctuation
- A single `final=true` chunk shows whole
- An empty final chunk marks the line done
- A late final chunk from an interrupted utterance doesn't end the new one

**`overlay/src/renderer/logic/layout.test.ts`** (add)
- `questionPlacement` picks the side with room

## 2. Test tooling to build

**Typed turns: `python -m brain --live --type`.** Each typed line becomes `PlayerSpeech`, so turns can be tested with no mic or Deepgram key. A prefix like `5: what's that` waits 5 seconds first, so there's time to switch back to the game. Capture stops while the terminal is in front, and `look_closer` refuses frames older than `look_max_frame_age_s`.

**Overlay demo: extend `scripts/overlay_demo.py`.** Send `subtitle.chunk` both ways, `toast.memory` and `question.ask`, so the new overlay parts can be checked with no brain logic.

## 3. Live checks

Run these in order. Each stage needs more keys. Stages 1 to 3 make paid or quota-limited calls. Tick results in `CLAUDE.md`.

### Stage 0: no keys
Run `python -m brain --live` and `npm --prefix overlay run dev`.
- [ ] Subtitle shows "Brain connected." once, then fades
- [ ] Reloading the overlay doesn't greet again
- [ ] The gear on the character opens settings, and clicking options updates them
- [ ] Settings survive restarting the brain
- [ ] The game still gets clicks everywhere except on buttons and card frames
- [ ] The overlay never takes keyboard focus while settings or a question is open
- [ ] Demo script: toast, question and subtitles look right, and their rectangles reach the brain's log

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
