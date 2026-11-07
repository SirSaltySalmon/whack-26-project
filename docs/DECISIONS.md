# Decision Log

Architectural decisions that change the plan. Add new entries at the top. Don't rewrite old ones: if a decision changes, add a new entry that replaces it, and mark the old one as replaced.

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
