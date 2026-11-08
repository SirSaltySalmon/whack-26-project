"""Messages go to the overlay that last said it was ready, never to one that only connected."""

import json
from typing import Any

from brain.events import EventBus
from brain.server import OverlayLink
from brain.tests.test_server import make, ready


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def rects(width: float) -> str:
    rect = {"element_id": "card", "rect": {"x": 0, "y": 0, "width": width, "height": 1}}
    return json.dumps({"type": "overlay.rects", "rects": [rect]})


async def test_a_socket_that_never_says_ready_gets_nothing() -> None:
    # React's abandoned dev socket: it connected, but its page never opened it.
    link = OverlayLink(EventBus())
    abandoned, live = FakeSocket(), FakeSocket()
    await link.handle_text(ready(), live)  # type: ignore[arg-type]
    assert [m["type"] for m in live.sent] == ["settings.state"]
    assert abandoned.sent == []
    assert link.connected


async def test_the_overlay_that_last_said_ready_gets_the_messages_and_neither_is_kicked() -> None:
    link = OverlayLink(EventBus())
    first, second = FakeSocket(), FakeSocket()
    await link.handle_text(ready(), first)  # type: ignore[arg-type]
    await link.handle_text(ready(), second)  # type: ignore[arg-type]
    first.sent.clear()
    second.sent.clear()
    await link.send(link.settings_state())
    assert first.sent == [] and len(second.sent) == 1
    # The first leaving doesn't disconnect the second.
    link.detach(first)  # type: ignore[arg-type]
    assert link.connected


async def test_only_the_drawing_overlays_rects_are_masked() -> None:
    link = OverlayLink(EventBus())
    first, second = FakeSocket(), FakeSocket()
    await link.handle_text(ready(), second)  # type: ignore[arg-type]
    await link.handle_text(rects(3), first)  # type: ignore[arg-type]
    assert link.rects == ()
    await link.handle_text(rects(5), second)  # type: ignore[arg-type]
    assert link.rects[0].width == 5


def test_an_overlay_is_reached_after_its_ready_over_a_real_socket() -> None:
    client, link, _ = make()
    with client.websocket_connect("/ws") as socket:
        assert not link.connected
        socket.send_text(ready())
        assert socket.receive_json()["type"] == "settings.state"
        assert link.connected
