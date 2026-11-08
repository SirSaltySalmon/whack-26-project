# Personalities

Status: drafted for wiring, and needs team review. The data is in [personalities.json](../brain/director/personalities.json). Degrading and Romantic are deliberately mild and family friendly until the boundaries below are decided.

The player picks one in settings, by clicking the gear on the character. Voice isn't tied to a personality yet.

| Personality | Idea |
|---|---|
| **Supportive** | Encouraging teammate |
| **Degrading** | Roasts the player's play |
| **Romantic partner** | Affectionate companion |
| **Protective** | Helps avoid mistakes and offers comfort |

## What each one holds

Each personality is swappable data: a tone, and short lines of these kinds.

| Kind | When it's used |
|---|---|
| `looking` | Before a tool runs |
| `done` | If a reply fails after a tool has run |
| `unavailable` | When it can't help |
| `danger`, `danger_high`, `died`, `low_health` | Reactions to game events, once barks are built (WP6) |

`event_lines` at the top of the JSON says which game event uses which kind.

## Rules for writing tones and lines

- **A personality is only a voice.** It never changes facts, whether the partner checks the screen, or whether it helps. The shared prompt in `brain/director/talker.py` says so for every personality. A tone or line must never refuse help or defend a mistake, because the partner copies its own earlier lines.
- At most 12 words, and short enough to say over gameplay.
- They must fit any game, so never name a game, enemy or item.
- **Reactions never give advice.** A bark is fixed text, so it can't follow the hints setting the way the talker does. "Your health looks low" is fine, and "find cover" isn't.
- **Say what it looks like, not what's certain,** because the partner's eyes can be wrong.

## Still to decide

- Boundaries for Degrading and Romantic
- Whether behavior changes when the player is tilted
- Which voice goes with each personality
