# Decision Log

Architectural decisions that change the plan. Add new entries at the top. Don't rewrite old ones: if a decision changes, add a new entry that replaces it, and mark the old one as replaced.

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
