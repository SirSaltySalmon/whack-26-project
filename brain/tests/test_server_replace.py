"""Only the newest overlay gets messages, and the one it replaced is closed so it can't linger."""

import pytest
from fastapi import WebSocketDisconnect

from brain.tests.test_server import make, ready


def test_a_newer_overlay_closes_the_one_it_replaces_and_gets_the_messages() -> None:
    client, link, _ = make()
    with client.websocket_connect("/ws") as first:
        with client.websocket_connect("/ws") as second:
            # The first was React's abandoned dev socket in a live run: it took the messages.
            with pytest.raises(WebSocketDisconnect):
                first.receive_json()
            second.send_text(ready())
            assert second.receive_json()["type"] == "settings.state"
            assert link.display_scale == 1.5


def test_the_same_socket_attaching_twice_replaces_nothing() -> None:
    _, link, _ = make()
    socket = object()
    assert link.attach(socket) is None  # type: ignore[arg-type]
    assert link.attach(socket) is None  # type: ignore[arg-type]
