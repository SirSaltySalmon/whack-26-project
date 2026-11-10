"""Add fictional screenshot data without changing real games' memory.

Run: python -m scripts.seed_showcase_memory
The dashboard game names identify these as samples. No models or microphones are used.
"""

import argparse
import logging
import sqlite3
import time
from pathlib import Path

from brain.config import Settings
from brain.memory.browse import browse, preview_context
from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.models import Source
from brain.memory.sessions import SessionStore
from brain.memory.unknowns import UnknownStore

log = logging.getLogger(__name__)
FactSeed = tuple[str, str, str, Source, float]

TERRARIA: list[FactSeed] = [
    ("player", "spoilers", "Hints first; no boss or progression spoilers", "player", 1.0),
    ("player", "playstyle", "Explores and builds before taking on bosses", "player", 1.0),
    ("home", "location", "Forest base, east of spawn", "observed", 0.78),
    ("world", "milestone", "Built a workshop with a furnace, anvil and storage", "observed", 0.88),
    ("player", "next goal", "Build a greenhouse above the workshop", "player", 1.0),
    ("player", "preferred weapons", "Bows for exploring caves", "player", 1.0),
    ("home", "location", "Forest base, west of spawn beside the lake", "player", 1.0),
]
MINECRAFT: list[FactSeed] = [
    ("player", "spoilers", "Let me discover structures; hint only when asked", "player", 1.0),
    ("home", "location", "Oak cabin beside the river near spawn", "player", 1.0),
    ("world", "milestone", "Built a wheat farm beside the cabin", "observed", 0.90),
    ("player", "next goal", "Find diamonds for an enchanting table", "player", 1.0),
    ("storage", "building supplies", "Chest beside the crafting table", "observed", 0.80),
    ("player", "next goal", "Build a bridge to the village before mining again", "player", 1.0),
    ("player", "building style", "Oak, stone brick and warm lantern lighting", "player", 1.0),
]
SAMPLES = [
    (
        "Terraria (showcase sample)",
        TERRARIA,
        "What are you saving the room upstairs for?",
        "The player explored a cave, brought ore home and added a furnace and anvil to the "
        "workshop. They prefer bows while exploring and want hints without progression spoilers.",
        "The next project is a greenhouse above the workshop. Corrected the base location: "
        "it is west of spawn beside the lake, not east. "
        "The upstairs room's purpose is still unknown.",
    ),
    (
        "Minecraft (showcase sample)",
        MINECRAFT,
        "Should the bridge match the cabin or the village?",
        "The player finished a wheat farm beside the riverside cabin and sorted building supplies. "
        "They like oak, stone brick and lanterns, and prefer discovering structures themselves.",
        "Plans changed: build the village bridge before returning to diamond mining. "
        "Building supplies were last seen beside the crafting table. Ask about the bridge style "
        "rather than assuming it should match the cabin.",
    ),
]


def seed_game(
    conn: sqlite3.Connection,
    game: str,
    entries: list[FactSeed],
    question: str,
    first_note: str,
    last_note: str,
    now: float,
) -> None:
    if conn.execute("SELECT 1 FROM sessions WHERE game = ?", (game,)).fetchone():
        log.info("Already exists: %s (left unchanged)", game)
        return
    clock = [now - 5400]
    sessions = SessionStore(conn, clock=lambda: clock[0])
    facts = FactStore(conn, clock=lambda: clock[0])
    session = sessions.start(game)
    for index, (subject, attribute, value, source, confidence) in enumerate(entries):
        clock[0] = now - 5100 + index * 420
        facts.remember(game, subject, attribute, value, source, confidence, session.id)
    sessions.add_note(
        session.id,
        "rolling",
        "[Fictional showcase session] " + first_note,
        session.started_at,
        clock[0],
    )
    clock[0] = now - 1200
    UnknownStore(conn, clock=lambda: clock[0]).wonder(
        game,
        "player",
        "open building question",
        question,
        session.id,
    )
    sessions.add_note(
        session.id,
        "recap",
        "[Fictional showcase session] " + last_note,
        session.started_at,
        clock[0],
    )
    sessions.end(session.id)
    found = browse(conn, game, "", True, 200)
    closed = sum(f.valid_to is not None for f in found.facts)
    log.info(
        "%s: %s current facts, %s historical, %s questions, %s notes",
        game,
        len(found.facts) - closed,
        closed,
        len(found.questions),
        len(found.notes),
    )
    if not preview_context(conn, game, ""):
        raise RuntimeError(f"Recall preview is unexpectedly empty for {game}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Settings().db_path)
    args = parser.parse_args()
    now = time.time()
    # SQLite's backup API includes committed WAL data; copying the main file alone may not.
    if args.database.exists():
        backup = args.database.with_name(f"showcase-backup-{time.time_ns()}.sqlite3")
        with sqlite3.connect(args.database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        log.info("Saved backup: %s", backup)
    conn = connect(args.database)
    try:
        for game, entries, question, first_note, last_note in SAMPLES:
            seed_game(conn, game, entries, question, first_note, last_note, now)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
