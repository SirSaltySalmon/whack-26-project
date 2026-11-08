"""Seeds a few facts, a question and a note so the Memory tab has something to show with no keys.

Writes through FactStore.remember, memory's only write path, so the trust rules apply: the class
change closes the old fact, the player overrules what was observed about their playstyle, and the
screen disputing the player's class becomes a conflict question.
Files everything under a test game title, never your real game. Meant to run once per title:
re-runs reuse the same backdated clock, so the class history gets odd timestamps.

    python .claude/skills/run-whack-26-project/seed_memory.py ["Control Center Test"]
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from brain.config import Settings  # noqa: E402
from brain.memory.db import connect  # noqa: E402
from brain.memory.facts import FactStore  # noqa: E402
from brain.memory.sessions import SessionStore  # noqa: E402
from brain.memory.unknowns import UnknownStore  # noqa: E402

FACTS = [
    ("player", "class", "Summoner", "player", 0.9),
    ("player", "favourite weapon", "Night's Edge", "player", 0.95),
    ("world", "hardmode", "not yet", "wiki", 0.6),
    ("player", "playstyle", "builds before fighting", "observed", 0.75),
    ("world", "bosses beaten", "Eye of Cthulhu", "observed", 0.85),
    ("player", "class", "Mage", "player", 0.9),
    ("player", "playstyle", "rushes bosses", "player", 0.8),
    ("player", "class", "Ranger", "observed", 0.7),
]


def main() -> None:
    game = sys.argv[1] if len(sys.argv) > 1 else "Control Center Test"
    conn = connect(ROOT / Settings().db_path)
    now = time.time()
    # Spread over the last hour, so the tab's "since" and "replaced" times differ. One time per
    # fact, not per clock read: a single write can read the clock several times.
    clock = [now - 3600]
    facts = FactStore(conn, clock=lambda: clock[0])
    row = conn.execute(
        "SELECT id FROM sessions WHERE game = ? ORDER BY id DESC LIMIT 1", (game,)
    ).fetchone()
    session = row[0] if row else None
    for index, (subject, attribute, value, source, confidence) in enumerate(FACTS):
        clock[0] = now - 3600 + index * 400
        result = facts.remember(game, subject, attribute, value, source, confidence, session)
        sys.stdout.write(f"{attribute}: {value} -> {result.outcome}\n")
    UnknownStore(conn).wonder(game, "player", "next goal", "What are you aiming for next?", session)
    if session is not None:
        SessionStore(conn).add_note(
            session,
            "rolling",
            "Beat the Eye of Cthulhu with a Night's Edge.\nSwitched from Summoner to Mage.",
            now - 600,
            now - 60,
        )
    conn.close()


if __name__ == "__main__":
    main()
