# Decision Log

Architectural decisions that change the plan. Add new entries at the top. Don't rewrite old ones: if a decision changes, add a new entry that replaces it, and mark the old one as replaced.

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
