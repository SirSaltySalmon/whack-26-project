-- Memory stores the play session, not a game encyclopedia. See docs/DECISIONS.md.

CREATE TABLE IF NOT EXISTS profile (
    game TEXT PRIMARY KEY,
    brief TEXT NOT NULL DEFAULT '',  -- What the game is, its goals and vocabulary. Learned as data.
    data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)),  -- regions, readers, entity_types
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL  -- NULL while playing, and also after a crash, so never treat it as "still live".
);
CREATE INDEX IF NOT EXISTS sessions_by_game ON sessions (game, started_at);

-- Notable moments plus conversation turns, whose names start with 'turn.'.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions (id),
    ts REAL NOT NULL,  -- Wall clock. Event.ts on the bus is monotonic and wouldn't survive a restart.
    name TEXT NOT NULL,
    data TEXT CHECK (data IS NULL OR json_valid(data))
);
CREATE INDEX IF NOT EXISTS events_by_session ON events (session_id, ts);

CREATE TABLE IF NOT EXISTS session_notes (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions (id),
    kind TEXT NOT NULL CHECK (kind IN ('rolling', 'recap')),
    body TEXT NOT NULL,  -- Markdown.
    from_ts REAL NOT NULL,
    to_ts REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS session_notes_by_session ON session_notes (session_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS session_notes_fts USING fts5 (
    body, content = 'session_notes', content_rowid = 'id', tokenize = 'porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS session_notes_ai AFTER INSERT ON session_notes BEGIN
    INSERT INTO session_notes_fts (rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER IF NOT EXISTS session_notes_ad AFTER DELETE ON session_notes BEGIN
    INSERT INTO session_notes_fts (session_notes_fts, rowid, body)
    VALUES ('delete', old.id, old.body);
END;

-- Claims about the player and this playthrough. Never enemy stats: those come from the wiki.
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    game TEXT,  -- NULL applies across games, such as "dislikes spoilers".
    session_id INTEGER REFERENCES sessions (id),
    subject TEXT NOT NULL COLLATE NOCASE,
    attribute TEXT NOT NULL COLLATE NOCASE,
    value TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('player', 'observed', 'wiki')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    tentative INTEGER NOT NULL DEFAULT 0,
    valid_from REAL NOT NULL,
    valid_to REAL  -- NULL while current. Old facts are closed, never overwritten.
);
CREATE INDEX IF NOT EXISTS facts_current ON facts (game, subject, attribute) WHERE valid_to IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5 (
    subject, attribute, value,
    content = 'facts', content_rowid = 'id', tokenize = 'porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts (rowid, subject, attribute, value)
    VALUES (new.id, new.subject, new.attribute, new.value);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, subject, attribute, value)
    VALUES ('delete', old.id, old.subject, old.attribute, old.value);
END;

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    game TEXT,
    session_id INTEGER REFERENCES sessions (id),
    text TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(options)),
    fact_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(fact_ids)),  -- Facts this answer settles.
    -- Set when the partner has no guess at all, so the answer knows where to be filed.
    subject TEXT COLLATE NOCASE,
    attribute TEXT COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'dropped')),
    answer TEXT,
    created_at REAL NOT NULL,
    asked_at REAL,
    answered_at REAL
);
CREATE INDEX IF NOT EXISTS questions_open ON questions (game, created_at) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS player (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value))
);

-- Lookup material, not memory. Page text is untrusted: sanitize it before display.
CREATE TABLE IF NOT EXISTS wiki_cache (
    api_url TEXT NOT NULL,
    page TEXT NOT NULL,
    title TEXT NOT NULL,
    html TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (api_url, page)
);
