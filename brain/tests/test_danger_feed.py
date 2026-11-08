import asyncio

from brain.danger_feed import forward_danger, level_after
from brain.events import EventBus, GameEvent, OverlayConnected
from shared.protocol.messages import BrainMessage, DangerState


def test_levels_follow_the_tracker_events() -> None:
    assert level_after("none", GameEvent("danger_started", {"level": "medium"})) == "medium"
    assert level_after("none", GameEvent("danger_started", {"level": "high"})) == "high"
    assert level_after("medium", GameEvent("danger_high")) == "high"
    assert level_after("high", GameEvent("danger_ended")) == "none"
    assert level_after("high", GameEvent("player_died")) == "none"
    assert level_after("medium", GameEvent("item_picked_up")) == "medium"


async def test_sends_changes_only_and_repeats_for_a_new_overlay() -> None:
    bus = EventBus()
    sent: list[BrainMessage] = []

    async def send(message: BrainMessage) -> None:
        sent.append(message)

    task = asyncio.create_task(forward_danger(bus, send))
    await asyncio.sleep(0)
    for event in (
        GameEvent("danger_started", {"level": "medium"}),
        GameEvent("item_picked_up"),
        GameEvent("danger_high"),
        GameEvent("danger_high"),
        OverlayConnected(display_scale=1.0),
        GameEvent("danger_ended"),
        OverlayConnected(display_scale=1.0),
    ):
        bus.publish(event)
    await asyncio.sleep(0.05)
    task.cancel()

    assert sent == [
        DangerState(level="medium"),
        DangerState(level="high"),
        DangerState(level="high"),
        DangerState(level="none"),
    ]
