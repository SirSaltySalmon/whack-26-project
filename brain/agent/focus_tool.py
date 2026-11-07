"""Lets a player turn ask the observer to watch the game more often for a few seconds.

Danger already boosts the rate by rule, so this is for what rules can't see, such as the player
saying "watch this". It only runs on player turns, so it can't be called more often than they talk,
and a repeat call just restarts the same short hold. The boost ends by itself; the talker hears
about that through its context, never as something to reply to.
"""

from typing import Literal

from pydantic import BaseModel, Field

from brain.agent.tools import Tool, TurnContext
from brain.perception.focus import Focus


class WatchInput(BaseModel):
    level: Literal["medium", "high"] = Field(
        description="medium for something worth following, high for fast action."
    )


def watch_tool(focus: Focus) -> Tool:
    async def watch(arguments: WatchInput, _turn: TurnContext) -> str:
        focus.boost(arguments.level, "player turn")
        return (
            f"Watching the game {arguments.level} for the next {focus.hold_s:.0f} s. It goes back "
            "to normal by itself, so there's nothing to say about it."
        )

    return Tool(
        "watch_closely",
        "Look at the game more often for a few seconds, at a higher cost. Use only when "
        "something exciting is starting that isn't already reported as danger, or the player "
        "asks you to watch.",
        WatchInput,
        watch,
        timeout_s=1.0,
        quick=True,
    )
