"""Saves a learned HUD profile as a fixture, for the demo fallback CLAUDE.md allows.

Usage: python scripts/export_profile.py [--game Terraria] [--out fixtures/profiles/terraria.json]
Learn the HUD live first (`python -m brain --live` with GAME_TITLE set), then run this. Load the
fixture on stage with PROFILE_FIXTURE=<path>; it's only used when nothing has been learned, and
the brain logs that it's a seeded profile. Say so if it's used on stage.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.config import Settings  # noqa: E402
from brain.memory.db import connect  # noqa: E402
from brain.memory.profile import ProfileStore  # noqa: E402

KEYS = ("regions", "readers", "learned_for")


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default=settings.game_title)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    conn = connect(settings.db_path)
    try:
        profile = ProfileStore(conn).get(args.game)
    finally:
        conn.close()
    if not profile.data.get("regions"):
        sys.exit(f"Nothing learned yet for {args.game!r}. Learn it live first.")

    slug = "".join(ch if ch.isalnum() else "-" for ch in args.game.lower()).strip("-")
    out = args.out or ROOT / "fixtures" / "profiles" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    fixture = {
        "brief": profile.brief,
        **{key: profile.data[key] for key in KEYS if key in profile.data},
    }
    out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    readers = ", ".join(reader["name"] for reader in fixture.get("readers", []))
    print(f"Saved {args.game!r} to {out} (readers: {readers or 'none'})")


if __name__ == "__main__":
    main()
