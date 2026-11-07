CREATE TABLE IF NOT EXISTS profile (
    game TEXT PRIMARY KEY,
    data TEXT NOT NULL CHECK (json_valid(data)),  -- regions, readers, entity_types
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    game TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (game, entity_type, name)
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER REFERENCES entities (id),
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('player', 'observed', 'wiki')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    tentative INTEGER NOT NULL DEFAULT 0,
    valid_from REAL NOT NULL,
    valid_to REAL  -- NULL while current. Old facts are closed, never overwritten.
);
CREATE INDEX IF NOT EXISTS facts_current ON facts (entity_id, attribute) WHERE valid_to IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5 (
    attribute, value, content = 'facts', content_rowid = 'id'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts (rowid, attribute, value) VALUES (new.id, new.attribute, new.value);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts (facts_fts, rowid, attribute, value)
    VALUES ('delete', old.id, old.attribute, old.value);
END;

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    data TEXT CHECK (data IS NULL OR json_valid(data))
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY,
    from_ts REAL NOT NULL,
    to_ts REAL NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'dropped')),
    answer TEXT,
    asked_at REAL,
    answered_at REAL
);

CREATE TABLE IF NOT EXISTS player (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
