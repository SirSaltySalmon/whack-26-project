import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.events import EventBus, OverlayConnected
from brain.server import OverlayLink, create_app
from shared.protocol import PROTOCOL_VERSION


def make() -> tuple[TestClient, OverlayLink, EventBus]:
    bus = EventBus()
    link = OverlayLink(bus)
    return TestClient(create_app(link)), link, bus


def ready() -> str:
    return json.dumps(
        {
            "type": "overlay.ready",
            "protocol_version": PROTOCOL_VERSION,
            "display_scale": 1.5,
            "width": 1280,
            "height": 720,
        }
    )


def test_ready_records_scale_and_publishes_event() -> None:
    client, link, bus = make()
    events = bus.subscribe()
    with client.websocket_connect("/ws", headers={"origin": "file://"}) as socket:
        socket.send_text(ready())
        assert socket.receive_json()["type"] == "settings.state"
    assert link.display_scale == 1.5
    assert isinstance(events.get_nowait(), OverlayConnected)


def test_rects_are_stored_and_invalid_messages_do_not_disconnect() -> None:
    client, link, _ = make()
    rect = {"element_id": "card", "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}
    with client.websocket_connect("/ws") as socket:
        socket.send_text("not json")
        socket.send_text(json.dumps({"type": "overlay.rects", "rects": [rect]}))
        socket.send_text(ready())
        socket.receive_json()
        assert link.rects[0].width == 3


def test_websites_are_refused() -> None:
    client, _, _ = make()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass
