# Decision Log

Architectural decisions that change the plan. Add new entries at the top. Don't rewrite old ones: if a decision changes, add a new entry that replaces it, and mark the old one as replaced.

## 2026-11-08: Memory can be read with the partner off, for any game

**Status:** built, tested, and checked in the Control Center against the real `data/brain.sqlite3`. Applies to `brain/memory/reader.py`, `brain/memory/browse.py`, `shared/protocol/control.py` (additive) and the Control Center's Memory tab.

- **A read-only reader process.** `python -m brain --memory` answers `memory.query`, `memory.context_preview` and the new `memory.list_games`, one JSON line each on stdin and stdout. It opens SQLite with `mode=ro`, so it never changes memory and can run beside a partner that's writing (WAL). It starts nothing else: no capture, voice or model. The Electron main process starts it on the first memory request made with no brain connected, and stops it after 5 idle minutes or when the window closes.
- **Same requests, either way.** With a brain connected, the Memory tab asks it over `/control` as before. Without one, `ControlContext.request` sends memory requests to the reader. The tab no longer needs the partner running.
- **Pick a game.** `memory.list_games` lists every game with sessions, facts, questions or a profile, played last first. `MemoryQuery` and `ContextPreview` take an optional `game`; none means the game being played, or the one played last. For a game other than the one being played, the recall preview is what its next session would start with: its last session's note, its facts, and no live state or turns.
- **Options rejected.** Reading SQLite from Node would duplicate the browse and recall logic in TypeScript, and the brain owns memory. A memory-only brain on the same port would look like a running partner to the other tabs, and would hold the port Start partner needs.

## 2026-11-08: Tips think briefly first, and the narration filter only trims an opening

**Status:** built on `main`, not yet run live. Applies to `brain/llm/claude.py`, `brain/llm/factory.py`, `brain/director/turns.py` and `brain/director/talker.py`.

- **The problem.** With thinking off, a live tip opened with the model's reasoning: "The player's on the character select screen, so there's no progress to build on yet." Anthropic documents this: with thinking disabled, the model may write its reasoning into the visible reply. Assistant prefill, the old way to force the reply's opening, returns a 400 on Haiku 5.5.
- **Tips think.** `LLMFactory.tips()` is the talker's model with adaptive thinking at low effort, in both the plain reply and the tool loop, which already sends thinking blocks back unchanged. Nobody waits on a tip, so the time doesn't matter. Haiku has no server-side fallback, so its clients never ask for one.
- **Player turns stay fast.** `TALKER_THINKING=true` turns thinking on for replies and player turns too. It costs time before the first word, so measure it with `scripts/latency_report.py` before choosing it for the demo.
- **The filter is a safety net, not the fix.** The first version dropped every sentence containing "the player", which would cut wiki answers phrased "The player can craft...". It now drops only the sentences a reply opens with, and only when they state the player's condition or intent ("The player's...", "The player is...", "The player wants..."). Later sentences, and facts phrased "can", "must" or "needs", are always kept.

## 2026-11-08: The overlay has swappable skins, and danger has one quiet look

**Status:** built on `main`, not yet run live. Applies to `overlay/src/renderer/skins/`, `brain/danger_feed.py` and `shared/protocol/messages.py`.

- **Skins are CSS, keyed on `data-skin` on the overlay's root.** Sticker (default), Island, Signal, Pixel, Broadcast and Classic, listed in `logic/skins.ts`. The player picks one in the overlay's settings card or the Control Center's Avatar tab, and both windows follow. It's saved in the overlay, like the avatar, so it works before the brain connects. Adding one is a stylesheet and a line in the list, never a branch in a component.
- **Danger looks the same in every skin:** a small black pill at the top for 4 s and one faint glow at the screen edges that fades within 2 s. Full-width banners and screen shakes were tried in mockups and rejected as too obtrusive during a fight. The pill is masked like any element. The glow isn't, because masking the screen edges would hide the game's health bars, which is why it's faint and brief.
- **`danger.state` (additive)** carries `none`, `medium` or `high`. `brain/danger_feed.py` forwards the tracker's `danger_started`, `danger_high` and `danger_ended` events, so the alert and the spoken line follow the same rule, and replays show it too. It's sent again when the overlay reconnects mid-fight.
- **Fonts are bundled** in `overlay/src/renderer/assets/fonts/` (Google Fonts, Open Font License), so the stage demo needs no network.

## 2026-11-08: Reactions are timed from the frame that showed them

**Status:** built on `main` (WP9), not yet run live. Applies to `brain/latency.py`, `brain/events.py`, `brain/perception/tracker.py`, `brain/perception/observer.py`, `brain/director/` and `brain/voice/`.

The prompt judges how fast the partner reacts to what happens on screen. `Latency: event to bark` started when the event was published, seconds after the frame for the observer, so it hid the slowest part.

- **`GameEvent.frame_ts`** is when the frame that first showed the event was captured. The tracker uses the first frame of the agreeing run, not the confirming one, because that's when it was first visible.
- **Reactions carry an `Origin`** (event, source, frame time, publish time) on `PlayBark` and `ReactToEvent`, with `compare=False`, so the rules' decisions and tests don't change.
- **Two log lines, split into noticed and spoke:** `frame to bark` when a bark's audio is queued, and `frame to first audio` when the voice really starts playing, for barks and talker lines alike. The old `event to bark` line stays, so earlier numbers can still be compared. `scripts/latency_report.py` and the Control Center's Latency tab parse these formats, so change all three together.
- **No number rather than a wrong one:** a line queued behind speech already playing isn't timed, because a later start could be credited to it. The player's next turn drops a pending timing, and audio starting more than 10 s after queuing isn't credited.
- **Replays don't record `frame_ts`:** monotonic times mean nothing in another process.

### What other tracks need to know

- `Voice.say` and `Voice.play` take a keyword `origin: Origin | None = None`. Any new voice or fake must accept it.
- After the WP4 merge, the reader engine should publish with `frame_ts` set to the first of its `confirm_reads` frames. Until then reader events log no frame latency.

## 2026-11-08: Questions are spoken and settle in the turn, the player wins corrections, and tips can point

**Status:** built on `main`, for the team to review. Applies to `brain/memory/`, `brain/director/`, `brain/agent/`, `brain/learner/`, `brain/voice/`, `overlay/`, and additively to `shared/protocol/`. Replaces part of "Low confidence means talk to the player" (2026-11-07): spoken answers no longer wait for the next session note.

Playtesting showed seven problems: questions came up as a popup, spoken answers rarely reached memory, unanswered questions came back, the mic couldn't be turned off, a corrected guess stayed wrong, questions were generic, and the partner almost never offered a tip or pointed at anything.

| # | Decision | Why |
|---|---|---|
| 1 | **Questions are spoken only.** The brain no longer sends `question.ask`, and the overlay has no popup | A popup covered the game and took the answer away from the conversation |
| 2 | **Player turns can write memory**: `answer_question`, `remember_fact`, `forget_fact` | A reply only reached memory through the next session note, which could time out and lose it. These run in the player's turn, need no extra model call, and only ever write source `player` |
| 3 | **The talker sees the question just asked** under `ASKED`, and fact keys as `subject / attribute` | So a reply can settle the right question, and a correction can close the wrong fact instead of adding a second one |
| 4 | **An unanswered question is dropped for good**: no reply within 20 s (45 s while typing), or 2 player turns that don't answer it. `wonder()` refuses any key already answered or dropped | The player moved on, so asking again would nag. The key stays unknown, and the talker says it doesn't know rather than guessing |
| 5 | **A player claim replaces an observed or wiki one.** Only the screen disputing the player opens a conflict question | Asking the player to choose between their own words and our guess was wrong. Authority is still player > observed > wiki |
| 6 | **Guesses from gear are stored tentative**, and the observer names things only when they're written on screen | Small icons in a downscaled frame are easy to misread, so the talker says "looks like" |
| 7 | **Each game gets planned questions**, drafted once by the deep model from the brief and kept in the profile | Questions in the game's own terms ("Have you beaten X yet?") instead of a generic fallback. Still data, so `brain/` stays game-agnostic |
| 8 | **Tips come sooner and more often**: the first after 90 s, then every 180 s, and 15 s after the partner learns where the player is (halved again, and made a setting, in "Pacing is a player setting" below). Quiet means no player turn and no partner line; game events no longer count | Game events arrive constantly in active play, so the old quiet window almost never opened |
| 9 | **A tip may point.** Advice runs through the agent with only `point_at` | Exception to "tools only on player turns": at most one vision call per tip, still bounded by the advice budget, and it never opens a page, so `page_url` stays player-requested |
| 10 | **The mic can be turned off** (`Settings.mic_enabled`), and the overlay has a text box that sends `player.text` | The brain treats a typed line exactly like speech, so watching, reacting and memory carry on |

### What other tracks need to know
- **Track 1 (Overlay):** the text box takes the keyboard only after the player clicks it, and hands it back to the game after sending.
- **Track 3 (Voice and director):** muting feeds Flux silence through `EchoGate`, so there's no barge-in from audio. Typed turns still barge in.
- **Track 4 (Memory and learning):** dropped questions use status `dropped`, so the schema is unchanged. `FactLearned` is published on the bus when a fact is stored, replaced or confirmed.

## 2026-11-08: Avatars are a gallery the overlay and Control Center share, without the brain

**Status:** built on `main`, for the team to review. Applies to `overlay/src/renderer/` only. Replaces the suggestion under "What other tracks need to know" below to send avatar choices through `Settings`.

| # | Decision | Why |
|---|---|---|
| 1 | **The circle is the default again; the cat stays as a built-in choice** | The player asked for it. Uploads sit after the two built-ins |
| 2 | **Uploads live in IndexedDB, the choice in localStorage** | Both windows load from the same origin, so they share both. A 512 px PNG is a few hundred KB, too many for localStorage's few MB |
| 3 | **A BroadcastChannel tells the other window to reload** | A pick or edit in either window shows in the other at once, with or without the brain. Through `Settings` it would only work while the brain runs, and images would cross the socket |
| 4 | **Each upload keeps its scaled original, and edits re-cut from it** | Remove background and mirror can be turned off again. Renaming doesn't re-cut |
| 5 | **The single picture saved before this moves into the gallery once**, as "My avatar", still chosen | Nobody loses their upload |

The overlay card picks and uploads. Editing is in the Control Center's Avatar tab (order 50), because a text field there can take the keyboard.

## 2026-11-07: A Control Center window configures, starts and inspects the brain

**Status:** built on `frontend`, for the team to review. Applies to `overlay/src/main/`, `overlay/src/renderer/control/`, `shared/protocol/control.py`, `brain/control.py`, `brain/describe.py`, `brain/server.py`, `brain/app.py` and `brain/__main__.py`, plus small additions in Track 3's and Track 4's directories listed below.

For the demo, one window has to show the technology: keys, game, personality and voice chosen before starting, a Start button, and memory browsed live with its sources and history.

| # | Decision | Why |
|---|---|---|
| 1 | **A second, normal window in the same Electron app** | Typing keys needs keyboard focus, and the overlay must never take it. The Control Center isn't always-on-top and never focuses itself on brain events |
| 2 | **It starts and stops the brain** | Choosing things before the start needs an owner. Closing the window stops the brain. A brain started from a terminal is still found and used |
| 3 | **Keys are encrypted with Electron `safeStorage` and passed as environment variables** | They're never written to `.env` and never sent back to the window. pydantic-settings reads the environment before `.env`, so `.env` still works as a fallback |
| 4 | **A new `/control` socket, not a second client on `/ws`** | `OverlayLink` keeps one socket, so a second client would replace the overlay. `/control` uses the same Origin allowlist |
| 5 | **Memory browsing is read-only** (`brain/memory/browse.py`) | Writes still only go through `FactStore.remember`, so the trust rules can't be bypassed |
| 6 | **Tabs are found from `overlay/src/renderer/control/tabs/*/tab.tsx`** | The avatar tab, and any later one, drops in without editing a shared file |
| 7 | **Stop asks over `/control` first, then ends the process tree after 5 s** | A plain kill skips `memory.finish()` and leaves the session open. On Windows, a venv's `python.exe` starts the real interpreter as a child, so it uses `taskkill /T` |

### What other tracks need to know
- **Track 1 (Overlay):** tabs follow `ControlTab` in `tabs/types.ts` and reach everything through `useControl()`. Order 50 is kept for the avatar tab. If avatar choices must reach the overlay, add an optional field to `Settings`, so they persist in memory like personality does. The in-game settings card and the Agent tab share `renderer/shared/SettingsFields.tsx`.
- **Track 3 (Voice and director):** `voice.preview` publishes `VoicePreviewRequested`, which the rules turn into a plain `Say`. It's skipped while the partner is talking.
- **Track 4 (Memory and learning):** `browse.py` reads `facts`, `questions` and `session_notes` directly, so schema changes there must update it. The recall panel calls the same `talker_context` the director uses.
- **Everyone:** `python -m brain --describe` must stay fast, so it imports only config and personalities, and `brain/__main__.py` imports `brain.app` only when running.

## 2026-11-07: A replay uses no live services unless asked

**Status:** accepted by Track 2's owner, for the team to review. Applies to `brain/replay/` and `brain/app.py`. Details are under WP3 in [REMAINING_WORK.md](REMAINING_WORK.md).

Replay is the test harness, so the same recording has to give the same result every time, on any machine, whatever is in `.env`.

| # | Decision | Effect |
|---|---|---|
| 1 | **Replies come from the recording** | `ScriptedTalker` hands out the recorded lines in order, leaving out questions, which the director asks itself. `REPLAY_LIVE_TALKER=true` asks the real talker instead |
| 2 | **Subtitles only, always** | Replay never opens the mic, so live speech can't mix with recorded speech, and it never spends TTS characters |
| 3 | **Session notes call no model** | Memory's recap would otherwise call Gemini when a replay ends. A replay's memory is thrown away anyway |
| 4 | **The recording's scale and settings win** | Masks use the recorded display scale even if a live overlay connects at another, and the partner speaks with the recorded personality and hints setting |

**Stays the same:** replay starts from `fixtures/replay_memory.sql` in memory, makes no vision calls, offers no tools, and doesn't show the game. The backup OBS recording is still the stage fallback for the game itself.

**Known limit:** lines come out in order, so if director rules change which events get a reply, later lines can answer the wrong thing. `compare_replay.py` shows where.



## 2026-11-07: How the HUD readers and learner judge what they read

**Status:** accepted by the project owner (empty bars, building WP5 with WP4, skipping scene matching); the rest are our defaults. Applies to WP4 (`brain/perception/readers.py`, `reader_rules.py`, `reader_engine.py`, `ocr.py`) and WP5 (`brain/learner/`).

- **An empty colour bar reads `unreadable`, never 0.** A bar that changes colour (hearts turning gold, say) looks the same as an empty one, and reading it as 0 would fire false low-health reactions. The observer keeps covering health while a reader can't.
- **Failing counts only during gameplay.** A reader counts as failing, and asks the learner to relearn, only after `reader_failing_after_s` unreadable while the observer confirms gameplay. Menus, death screens and our own masks don't count. Readers whose rules are all `above` (things that come and go, like a boss bar) never count as failing, and re-arm once they've been gone for 3 reads. This decides by rule type, not by name, so it stays game-agnostic.
- **Bars are measured by how far the colour reaches,** not by an unbroken run, so segmented bars, rows of icons and text over a bar still read. A column counts when 30% of it matches.
- **OCR skips text detection for numbers.** RapidOCR's recognition alone read `72/100` in about 15 ms; with detection it took about 850 ms. Regions are already cropped to the text. Only multi-line `ocr_text` uses detection. OCR has its own thread and is skipped while busy, so it never delays colour readers.
- **A changed game size pauses readers** and asks for a relearn, because many games pin their HUD in pixels, so fractions of the frame move when the window does.
- **Reader values go straight after mood in the talker's context,** ahead of the observer's text, which memory would otherwise cut first. A reader replaces the observer's value for the same key, and the observer stops publishing events working readers cover, though its focus boosts still see them.
- **The learner waits for gameplay.** It doesn't start a pass, or spend a vision call, until a fresh gameplay frame exists.
- **The debug view hides its labels from vision but not its outlines.** Outlines sit outside each box, so they can't mask a reader or change what it reads. Labels carry values, so they're masked like any overlay text.

## 2026-11-07: Look less often by default, and faster for a few seconds when it matters

**Status:** accepted by the project owner, who asked for the levels; the details below are ours. Changes the 0.8 s rate in the Haiku entry below. Applies to `brain/perception/focus.py`, `brain/perception/observer.py`, `brain/agent/focus_tool.py` and `brain/config.py`.

Most of the time nothing is happening, so reporting every 0.8 s paid for frames that said the same thing.

- **Three levels:** low every 1.3 s (the default), medium every 0.8 s and high every 0.6 s. A boost lasts 5 s (`focus_hold_s`) and then drops back by itself. Repeating a boost restarts the hold rather than adding to it.
- **Danger boosts by rule, with no model call.** One frame reporting danger boosts to medium once its reply arrives, so the frames that follow come sooner. Confirmed danger holds medium or high for as long as it lasts, and low health holds high. This covers most exciting moments without the talker doing anything.
- **The talker can boost with `watch_closely`,** for what rules can't see, such as the player saying "watch this". Tools only run on player turns, so it can't be called more often than the player talks. It's a quick tool, so it doesn't say "one sec" or block a barge-in. Its only extra cost is the follow-up model call any tool needs.
- **The talker is told, not prompted.** While a boost runs, and for 15 s after it ends, its context says so. The end isn't an event, so it never makes the partner speak, and the wording tells it there's nothing to act on.
- **A boost wakes the observer early.** A boost during a 1.3 s wait reports straight away, rather than finishing the wait.
- **Costs:** about $1.15 an hour at low, $1.85 at medium and $2.45 at high. The Haiku spending cap rose from 90 to 120 a minute to fit high plus `look_closer`. Up to 5 requests can be in flight, up from 4.
- **Slower to notice danger at low:** the second, confirming frame goes out 1.3 s after the first rather than 0.8 s, before the first reply can boost anything, so confirmed danger arrives about 0.5 s later. Lower `observer_interval_low_s` if that's too slow on stage.

## 2026-11-07: Replies stay short unless the player asks for more

**Status:** accepted by the project owner. Replaces the 12-word hard cap (decision 2 of the voice entry below still holds: a reply is collected before TTS). Applies to `brain/director/talker.py`, `brain/agent/turn.py` and `brain/config.py`.

A hard 12-word cap leaves no room for an answer the player asks to hear in full, such as how a mechanic works.

- **The default stays short.** The prompt asks for about one 12-word sentence, like a teammate talking mid-game.
- **Longer only when asked.** If the player asks to explain, elaborate or give details, the reply can run longer.
- **A hard cap of 100 words** (`talker_max_words`), enforced in code. Token limits rose to fit: 200 for plain replies and 400 for tool turns.
- **Longer answers take longer to start.** A reply is collected whole before TTS, so a 100-word answer delays first audio more than a short one. Short replies are unaffected.

## 2026-11-07: A turn that's using a tool finishes, even if the player talks

**Status:** accepted. Narrows decision 4 of the agent entry below ("a barge-in cancels the turn in progress"). Applies to `brain/director/` and `brain/agent/`.

In the first live test, every request that used `look_closer` spoke its "one sec" line and then never answered. The logs showed why: the check took about 9 s, the player talked again within 4-6 s, and that barge-in cancelled the turn and threw the answer away.

- **Tool turns survive a barge-in.** Once a turn has started a tool, the player talking doesn't cancel it. A new question waits until it has answered.
- **The answer waits for silence.** It's said once the player stops talking, or dropped after 10 s if they don't.
- **`look_closer` uses Haiku** (`closeup_model`), which should take about 1.5 s, instead of Gemini Flash at full resolution, which took 9.1 s on a Terraria screenshot. These calls only happen when the player asks. Without `ANTHROPIC_API_KEY` it falls back to `vision_model`. `point_at` stays on Gemini, because `coords.py` converts its box format.
- Turns without tools still cancel on a barge-in, as before.

## 2026-11-07: The partner can read the open page, on the game's wiki only

**Status:** accepted by the project owner, not built yet. Partly replaces "the wiki window shows the real site" below: page text may now reach a model in this one case. Frames stay masked. The spec is WP8 in [REMAINING_WORK.md](REMAINING_WORK.md).

If the player has the answer open, the partner shouldn't need another call to find it. Today it can't see the page at all, and `lookup_wiki` only fetches an intro and infobox.

| # | Decision | Effect |
|---|---|---|
| 1 | **Read rendered text, not HTML** | `innerText` is much smaller, and leaves out markup and text hidden by CSS. Table layout is lost, though rows stay readable |
| 2 | **Only the game's discovered wiki** | The brain asks for a read only when the open page's hostname exactly matches. A page off the wiki is never read, and the partner says it can't. This limits prompt injection and what reaches Gemini's free tier, at the cost of not reading a guide the player followed a link to |
| 3 | **Match locally, then offer a tool** | Keyword matching adds relevant passages to the first prompt, so a page question usually takes one Flash-Lite call. `read_open_page` gets more for one extra call. Reaching zero isn't possible, because a model still writes the reply |
| 4 | **Read when the player starts speaking** | The text is fresh, nothing polls and the voice path never waits |
| 5 | **Player turns only, in RAM only** | Page text never reaches game-event reactions or SQLite. It's labelled as tentative data |
| 6 | **The script runs in an isolated world, from the main process** | The page's own scripts can't tamper with it, and the sandbox stays as it was: no preload |

Rejected: tool only (every page question takes two calls), an excerpt on every turn (sends page text on unrelated turns), and raw HTML (large, and hidden text would need catching separately).

The matching can miss, or pick the wrong passage. A miss costs one tool call. A wrong passage could mislead the reply, which is why the text is labelled tentative.

## 2026-11-07: Hints off means conversation only, and barks replace the talker where they fit

**Status:** accepted by the project owner. Applies to `brain/director/` and the overlay's settings.

**Hints off isn't silence.** The first version stopped game reactions and questions when hints were off. A partner that goes quiet doesn't feel like one, and it still has to ask to understand the game.

- The director's rules no longer take the setting, so reactions and questions run either way, under the same cooldown and question budget.
- The setting only changes the prompt. Off, the talker is told not to offer hints, tips or anything the player hasn't found yet, and to give game knowledge only when asked directly.
- This relies on the model following that instruction, so test it. It isn't enforced in code.

**Barks replace the talker for the events they cover,** once WP6 in [REMAINING_WORK.md](REMAINING_WORK.md) is built. Speed is the point of a reaction, at the cost of less variety. With no bark ready, the event falls back to the talker.

## 2026-11-07: Player turns can use tools, and MCP is a later adapter

**Status:** accepted by the project owner, for the team to review. Applies to `brain/agent/`, `brain/director/` and `brain/llm/`.

Every part of the idea was built, but the partner could only talk. Nothing in the brain sent a pointer, opened the wiki, looked closer at a frame or asked a question.

| # | Decision | Effect |
|---|---|---|
| 1 | **The talker's model can call tools, on player turns only** | A plain reply still takes one model call. Game events use the old path with no tools, so they can't start a run of vision calls, and `page_url` is only ever sent because a player asked |
| 2 | **Rules still decide when to speak** | The model only chooses what to do inside a turn the director started. This doesn't change the rule against an LLM deciding when to talk |
| 3 | **Tools are plain in-process functions** | `brain/agent/tools.py` holds a name, description, Pydantic input and handler for each, which is also the shape an MCP server needs |
| 4 | **Speech runs in its own task, with one slot** | The director's decisions stay instant. A player turn replaces what's in the slot, and their next start of turn cancels it |
| 5 | **The model running the turn never sees images** | `look_closer` and `point_at` make their own vision call and return text. This keeps the turn's context small and vendor-neutral |
| 6 | **Gemini Flash-Lite runs player turns** | Free, with no new key. Its tool choices and quota are unproven, so see the [test plan](TEST_PLAN.md). The model is one config value |

### Why not MCP now
MCP still works as a later addition, but it wouldn't have closed this gap, because what was missing was tool calling.

| Option | Result | Reasoning |
|---|---|---|
| **In-process registry** | **Chosen** | The tools need the ring buffer, overlay link and database connection, which are all objects inside the brain |
| Pipecat's `MCPClient` | Rejected | It attaches tools to an LLM context in the pipeline, which we removed on purpose. In 1.15 it also keeps only text results (`mcp_service.py`, `_call_tool_text`), so an image tool would return nothing |
| Anthropic's MCP connector | Rejected | It needs a URL Anthropic's servers can reach, which would expose game frames |
| A separate MCP server process | Rejected | It couldn't reach the brain's in-memory frames |

**To add MCP later:** wrap `ToolRegistry` in an MCP server inside the brain. Do this when something outside the brain needs the tools, such as Claude Code. A localhost endpoint would serve game frames, so it needs the same origin checks as the overlay's WebSocket.

### Also checked in Pipecat 1.15
The no-LLM pipeline holds up against the source. With no aggregator, Flux's turn proposals interrupt nothing, so `TurnBridge`'s manual `broadcast_interruption()` is required, not a workaround. No official example runs this layout, and it hasn't been run live yet.

### What other tracks need to know
- **Track 1 (Overlay):** subtitles, toasts, questions and settings are built. `settings.state` gains `personalities` and `voices`. Settings and answers use buttons only, so the keyboard stays with the game.
- **Track 2 (Capture and perception):** `perception/closeup.py` makes the masked crops, and `encode_jpeg` moved there from the observer. Readers and replay are still yours.
- **Track 3 (Voice and director):** the director now cancels speech by itself, and `Voice.say()` returns whether it spoke. Filler lines go through TTS for now, so pre-generated barks still need doing.
- **Track 4 (Memory and learning):** `take_question()` and `wonder()` are now called. Nothing writes the game brief yet, so the talker's context has no game description.

## 2026-11-07: Haiku watches the screen continuously, and only agreeing frames count

**Status:** accepted by Track 2's owner, for the team to review. Replaces "call vision only on a trigger" for screen awareness. Applies to `brain/perception/`, `brain/llm/` and the director.

The partner needs to stay aware of what's on screen and notice anything important, in any game. Waiting for a trigger can't do that, because something has to notice the trigger first.

**Model.** Claude Haiku 5.5 reports on the newest frame every 0.8 s, using 1280-wide images and structured output. We compared it with Moondream 3.1 on 30 screenshots from five games. Haiku noticed all 14 fights and read all 10 health values. Moondream, even with focused prompts and crops, noticed 4 fights and read no health values, while needing five calls per frame. It costs about $1.85 an hour, and only runs with `ANTHROPIC_API_KEY` set and the game in front. Gemini's free tier can't sustain the request rate.

**Confirmation.** The model hallucinates, so a report only counts once consecutive frames agree (`brain/perception/tracker.py`). We asked about 12 tricky frames five times each:

| | Fight frames | Calm frames |
|---|---|---|
| Single read at medium or high danger | 20 of 20 | 3 of 40 |
| Two reads in a row at medium or high | 80 of 80 | 2 of 160 |

So it removes flicker without missing fights. It doesn't remove stubborn mistakes: one frame gave a friendly NPC as a "Blue Slime" threat in 5 of 5 reads, and a Hades coin counter was probably read as "23 / 100" health in 5 of 5. Confirmed therefore means stable, not true:

- Only medium or high danger raises an event. Low danger stays quiet.
- Threat names must match between frames before they're used.
- Danger clears after three calm frames, so a brief lull doesn't end a fight and restart it.
- The talker is told its eyes can be wrong. Reports stay in RAM as live state and don't become stored facts.

**Effect on tracks.**
- **Track 2:** the observer is the source of live state until compiled readers exist. Readers remain the path to reactions under a second, because a confirmed report is about 2.4 s old.
- **Track 3:** confirmed changes arrive as `GameEvent`s named `danger_started`, `danger_high`, `danger_ended`, `health_low` and `player_died`. The director now sends them to the talker with the live context, rather than speaking a placeholder. Pre-generated barks can replace that where they fit.
- **Track 4:** those events reach session notes as usual. The talker now uses `MemoryService.context()`, and the partner's replies are recorded. The live-state character cap went from 200 to 340, since sight and mood both land there.

**Voice additions.** Flux has no sentiment, so `brain/voice/sentiment.py` scores the live transcript with VADER and adds loudness and speech rate. It's a rough signal that colours replies and decides nothing. The voice also publishes partial transcripts, listens without ElevenLabs keys, and can't take the brain down if it fails to start.

## 2026-11-07: The game profile has no `entity_types`

**Status:** accepted. Applies to `brain/learner/`, `brain/research/` and `brain/memory/`.

Nothing read `entity_types`, and it overlapped with the `entities` table that was already removed. The profile now holds the brief, regions and readers. Game vocabulary goes in the brief, where the talker already sees it.

## 2026-11-07: The voice pipeline holds no LLM

**Status:** accepted. Logged after the voice work merged. Applies to `brain/voice/` and `brain/director/`.

The director has to stay in charge of when the partner speaks, so Pipecat only turns speech into bus events and text into audio.

| # | Decision | Effect |
|---|---|---|
| 1 | **The director calls the talker, then passes text to TTS** | The pipeline has no LLM or user aggregator. Barge-in starts from Flux's start of turn |
| 2 | **A talker reply is collected before TTS** | Generation stops once the reply passes the 12-word cap. TTS doesn't start until then, so stream by sentence only if measured latency misses the 1 s budget |
| 3 | **Subtitles are read after the audio output** | Words reach the overlay as their audio plays, which keeps them in step |
| 4 | **Half-duplex mode is available for playing without headphones** | `VOICE_HALF_DUPLEX=true` feeds Flux silence while the partner talks. Headphones remain the default, because this mode gives up barge-in |

### What other tracks need to know
- **Track 1 (Overlay):** with real voice, words arrive as `final=False` chunks, then an empty `final=True` chunk ends the utterance. Subtitles-only mode sends one chunk with the whole text and `final=True`. Handle both.
- **Track 4 (Memory and learning):** the talker doesn't use memory yet. `MemoryService` already exposes what it needs.

## 2026-11-07: Frames reach the AI only on a trigger

**Status:** replaced for screen awareness by "Haiku watches the screen continuously" above. Still applies to Gemini vision. Logged after the fact. Replaces the original plan's downscaled video stream of about 1 fps. Applies to `brain/capture/`, `brain/perception/` and `brain/learner/`.

Free-tier quotas won't sustain any continuous stream to a vision model, even at 1 fps. The original goal of selective ingestion stays, but the selection now happens locally.

- Frames are captured at about 5 fps into a 10-second, full-resolution ring buffer in RAM. They don't leave the machine by default.
- Compiled local readers watch those frames, so fast reactions never wait on a model.
- Vision is called only when learning the game, when the player asks, or when an event fires. Frames are downscaled by default, and full-resolution crops are only sent when the player asks or an event fires.

## 2026-11-07: The wiki window shows the real site

**Status:** accepted. Replaces the earlier rule against loading live web pages in the overlay. Applies to `overlay/`, `shared/protocol/` and how `brain/` opens pages.

### Why the plan changed
The player should be able to open, read, minimize and navigate the actual wiki while playing. A sanitized text card can't do that.

The earlier rule mainly guarded against two risks, and both can be handled another way:
- **Page text reaching the model:** the window's rectangle is masked like every other overlay element, so its content never reaches a model.
- **Third-party code in the overlay:** the page runs in a sandbox with no access to the app. The brain's WebSocket already refuses connections from websites.

### Decisions

| # | Decision | Effect |
|---|---|---|
| 1 | **Use `<webview>`, sandboxed** | No preload, no Node, no popups, no permissions, no downloads, in-memory session, http(s) only |
| 2 | **Links stay in the window, wherever they go** | The window isn't limited to the wiki's host, so the sandbox is the protection. Links that would open a new window load in this one |
| 3 | **`body` stays as the fallback** | `card.show` gains an optional `page_url`. If the page can't load, the window shows `body` as text, so research still works offline |
| 4 | **One wiki window** | A new lookup reuses it. Minimizing keeps the page and scroll position |
| 5 | **Only player-requested lookups open or change the page** | The partner can't navigate away while the player is reading |
| 6 | **The character moves by a hover grip** | Its body stays click-through, because the game aims with the mouse. A 3:4 placeholder stands in until there's art |
| 7 | **The overlay doesn't take keyboard focus** | `focusable: false` until the player chooses to type |
| 8 | **The pointer doesn't track moving targets** | It sits beside the target and fades after `ttl_ms`. It points at what it can find on screen |

### Options considered for the window

| Option | Result | Reasoning |
|---|---|---|
| **A. `<webview>`** | **Chosen** | Has back, forward and page events built in, isn't stopped by `X-Frame-Options`, and is drawn as part of the page. The tradeoff is that Electron's docs warn it can be unstable |
| B. Sandboxed `<iframe>` | Fallback | wiki.gg sent no framing headers when checked with curl, but Fandom sent `X-Frame-Options: SAMEORIGIN` on a Cloudflare challenge. Navigation controls would have to be built through the main process |
| C. `WebContentsView` | Rejected | It's expected to draw above the DOM, so the pointer and subtitles would pass behind it. Not tested |
| D. Sanitized text card only | Rejected | Can't read and navigate the real site. Remains the offline fallback |

### What stays the same
- Wiki text, OCR text and web results are still data, never instructions to the model.
- Fetched pages are still lookup material, not memory.
- `setContentProtection` is still banned, and the overlay must still appear in recordings.

### What other tracks need to know
- **Track 2 (Capture and perception):** elements can now sit over the HUD, and masks are filled with black. A reader whose region is masked must report the value as unknown, or a covered health bar could read as empty.
- **Track 3 (Voice and director):** send `page_url` only for lookups the player asked for. Set a short `ttl_ms` on `pointer.fly` for world targets, because the world may scroll during the vision call.
- **Track 4 (Memory and learning):** `card.show` still needs a sanitized `body` as the fallback. `card.navigated` reports which page is open, and its URL and title are untrusted.

## 2026-11-07: Replay runs start from a fixed memory snapshot

**Status:** accepted. Applies to `brain/memory/` and `brain/app.py`.

Replay is both the main test harness and the stage fallback, so its memory has to be repeatable and able to show the partner remembering earlier sessions.

- Each replay loads `fixtures/replay_memory.sql` into an in-memory database, and everything it learns is thrown away when the run ends. The player's real memory is never touched, and the vault isn't exported.
- If the file is missing or can't be loaded, the replay still runs, with empty memory.
- The snapshot is SQL text rather than a database file so it can be reviewed. It can contain conversation transcripts, so read it before committing it.
- If a snapshot is used on stage, say that its memory was seeded.

## 2026-11-07: Low confidence includes not understanding the game yet

**Status:** accepted. Applies to `brain/memory/` and the talker's context.

Low confidence isn't only a shaky reading that disagrees with a stored fact. The partner often just hasn't discovered a detail yet, and that's a reason to talk to the player rather than guess.

| Situation | What happens |
|---|---|
| The partner has no guess: "what's shimmer?" | Opens a question with no fact behind it, and the player's answer becomes a `player` fact |
| The partner has a shaky guess and nothing stored | Stores it as tentative and asks yes or no |
| A shaky reading disagrees with a stored fact | Keeps both open and asks, so it can't replace something surer |

- Open questions appear in the talker's context under `UNSURE`, so it can say it doesn't know or bring them up instead of guessing.
- Spoken answers count. Replying after a question brings the next session note forward, and that note settles the question. This adds no separate LLM call beyond that note.
- Session notes can also open questions about things the partner didn't follow.
- At most five of these no-guess questions stay open at once, and asking still goes through the director's question budget, so the partner doesn't nag.

## 2026-11-07: Memory stores the play session, not a game encyclopedia

**Status:** accepted. Applies to `brain/memory/`, `brain/research/` and the talker's context.

### Why the plan changed
The original plan treated memory as a broad fact graph, with game entities, enemy stats and wiki claims all stored as facts. That's more than the partner needs.

The partner needs memory so it can understand the game and talk naturally about what's happening in this playthrough. Enemy stats are already on the wiki and can be looked up when needed. What it can't look up is what happened in this session, what the player wants and how the player likes to play.

The original comparison of memory stores assumed a single game. Its ranking still holds for a game-agnostic partner, because that changes what we store, not where we store it. SQLite remains the best fit, and Obsidian remains "poor as a store, good as a view".

### Decisions

| # | Decision | Effect |
|---|---|---|
| 1 | **Session notes are the core of memory** | `summaries` becomes `session_notes`, written from notable events and conversation. A new `sessions` table groups them |
| 2 | **Notes are Markdown stored in SQLite, with a one-way export to an Obsidian vault** | One store, atomic writes and one search index, with a readable "brain" to show in the demo. SQLite stays the source of truth |
| 3 | **Facts only cover the player and this playthrough** | For example "plays summoner" or "base is east of spawn". Every fact still keeps its source, confidence and validity window |
| 4 | **The wiki is lookup material, not memory** | Fetched pages go in a `wiki_cache` table. A wiki claim becomes a fact only when it matters to the playthrough, and it stays tentative until confirmed |
| 5 | **Live game state isn't stored as facts** | Readers keep values like health in RAM, and the talker receives the fresh value. Only notable moments are logged as events |
| 6 | **The `entities` table is removed** | Facts use a plain `subject` text column, which is simpler and makes subjects searchable |
| 7 | **Each game has a short brief in its profile** | The brief covers what the game is, its goals and its vocabulary. It's learned as data, so `brain/` still has no game-specific logic |
| 8 | **The talker's context is a small assembled block** | Game brief, live state, this session, last session, relevant player facts and the last few turns. It never gets raw session history |

### Options considered for the hybrid

| Option | Result | Reasoning |
|---|---|---|
| **A. Markdown notes in SQLite, exported to a vault** | **Chosen** | Keeps the useful part of Obsidian, a short index plus linked notes loaded on demand, without running two stores. The tradeoff is that edits made in Obsidian don't flow back |
| B. Markdown files for notes, SQLite for everything else | Rejected | Lets the player edit memory directly, but needs two stores kept in sync, file watching and reindexing. That isn't worth it unless hand-editing is part of the demo |
| C. SQLite only, with no export | Rejected | Loses the readable view that helps show what the partner remembers |

### What stays the same
- SQLite is the source of truth, and the authority order is still player > observed > wiki.
- Old facts are closed, never overwritten, and conflicts between trusted sources still go to the player.
- Questions still go through the director with their own budget.
- sqlite-vec and fastembed are still first on the cut list, so FTS5 has to work well on its own.
- `shared/protocol/` doesn't change: `toast.memory` and `question.ask` are still the overlay's only memory messages.

### What other tracks need to know
- **Track 1 (Overlay):** nothing changes.
- **Track 2 (Capture and perception):** readers remain the source of live state. Only notable moments need to become `GameEvent`s.
- **Track 3 (Voice and director):** the talker gets its context from memory instead of building its own, and the director still owns the question budget. The exact interface will be agreed with Track 3.
- **Track 4 (Memory and learning):** the schema is being rewritten. Local databases created from the old schema must be deleted.

## 2026-11-08: Claude Haiku for every fast role
**Change:** the talker, player turns with tools, pointing and the progress scout move from Gemini (Flash-Lite and Flash) to Claude Haiku 5.5 with thinking off, joining the screen reports and `look_closer` already on it. Sonnet 5.5 stays on deep reasoning.

**Why:** one vendor and one key for everything the player waits on, without free-tier quotas.

**How:** `LLMFactory` picks the vendor from the model name: `claude-*` runs on Anthropic, anything else on Gemini, so going back is a change to `talker_model` or `vision_model`. All Haiku roles share one rate limiter, raised to 240 a minute.

**Unproven:** whether Haiku's `box_2d` boxes (0-1000, `[ymin, xmin, ymax, xmax]`) are as accurate as Gemini's. Check with `scripts/check_pointing.py`.

## 2026-11-08: Meaning-based memory search, switchable in settings
**Change:** recall can match by meaning as well as by keywords. Settings has a new "Memory search" choice, `memory_search` in the protocol: Keywords (`keyword`, the default and the old behavior), Both (`hybrid`) and Meaning (`semantic`).

**Why:** FTS5 matches words, and speech paraphrases. "Where's my house?" never found `base / location` by keywords.

**How:**
- `brain/memory/semantic.py` loads the model in the background only when the player picks Both or Meaning, embeds new facts and note lines, and embeds each question on its own thread. Every failure falls back to keywords.
- `brain/memory/vectors.py` keeps sqlite-vec tables next to the facts and notes. They're derived data: created at runtime, so there's no schema bump and no need to delete databases, and rebuilt if the model changes. Search is an exact scan rather than vec0's nearest-neighbour query, because that query picks neighbours before filtering out closed facts and other games.
- Both merges keyword and meaning results by reciprocal rank fusion, so the two scores never need to be on one scale.
- Replays stay on keywords, so a stage fallback never waits on a model download.

**Model:** `sentence-transformers/all-MiniLM-L6-v2`, not the `BAAI/bge-small-en-v1.5` the architecture first named. On 12 questions against our facts, bge-small scored unrelated questions as high as related ones (0.62 for "tell me a joke"), so no cutoff could separate them. MiniLM scored unrelated questions at most 0.22 and related ones mostly 0.28 or more, so `recall_min_similarity` is 0.25. snowflake-arctic-embed-xs was worse than both.

**Measured on the main dev machine:** model load about 0.2-0.4 s once cached, a question about 4-20 ms, `context()` about 4.5 ms in Both against 1 ms in Keywords. The first use downloads about 90 MB into `data/models`, so run it once before the demo.

**Limit:** the talker already gets the newest 8 facts, and recall skips those, so this only adds anything once memory holds more than that, or for older session notes.

## 2026-11-08: Pacing is a player setting, and questions and tips come about twice as often
**Change:** the gaps that decide when the partner speaks unasked moved from `brain/config.py` into the player's settings, as `Settings.pacing` (`Pacing` in `shared/protocol/messages.py`, an additive change). The Control Center has a Pacing tab to edit them, with Lively, Default and Calm presets. Reactions keep their 8 s gap; questions and tips come about twice as often:

| Setting | Was | Now |
|---|---|---|
| Between event reactions (`event_gap_s`, the director's bark cooldown) | 8 s | 8 s |
| Between questions (`question_gap_s`) | 90 s | 45 s |
| Quiet before a question (`question_quiet_s`) | 20 s | 0 s, so only the 45 s gap applies |
| First tip (`advice_first_s`) | 90 s | 45 s |
| Between tips (`advice_gap_s`, 0 turns tips off) | 180 s | 90 s |
| Quiet before a tip (`advice_quiet_s`) | 20 s | 10 s |

**Why:** the partner should ask and advise more often, and the right pace is easier to find by trying it while playing than by editing config and restarting.

**How:** the director's rules take the new pacing on `SettingsChanged`. A shorter tip gap brings a tip already scheduled forward, so the change is felt at once; a longer one never pushes a due tip back. Rules stay deterministic and tested (`brain/tests/test_pacing.py`). Calm keeps the old values. `advice_after_learning_s` stays in config.

**Without a quiet stretch,** a question is still never asked over the partner (ticks skip a busy speech slot), is held while the player is mid-sentence, and waits out danger. The first can come right after the greeting, since only the gap between questions applies.

**Watch for:** tips still wait for quiet since anyone last spoke, so a shorter event gap would mean more reactions and fewer tips.
