# Decision Log

Architectural decisions that change the plan. Add new entries at the top. Don't rewrite old ones: if a decision changes, add a new entry that replaces it, and mark the old one as replaced.

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
- **Track 4:** those events reach session notes as usual. The live-state character cap went from 200 to 340, since sight and mood both land there.

**Voice additions.** Flux has no sentiment, so `brain/voice/sentiment.py` scores the live transcript with VADER and adds loudness and speech rate. It's a rough signal that colours replies and decides nothing. The voice also publishes partial transcripts, listens without ElevenLabs keys, and can't take the brain down if it fails to start.

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
