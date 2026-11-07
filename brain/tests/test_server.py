import json
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.events import CardPageChanged, EventBus, OverlayConnected, SettingsChanged
from brain.server import OverlayLink, create_app
from brain.tests.fakes import drain
from shared.protocol import PROTOCOL_VERSION
from shared.protocol.messages import Settings, VoiceOption


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


def test_page_changes_reach_the_bus() -> None:
    client, _, bus = make()
    events = bus.subscribe()
    page = {"type": "card.navigated", "card_id": "wiki", "url": "https://a.example/", "title": "A"}
    with client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps(page))
        socket.send_text(ready())
        socket.receive_json()
    assert events.get_nowait() == CardPageChanged(
        card_id="wiki", url="https://a.example/", title="A", ts=ANY
    )


def test_websites_are_refused() -> None:
    client, _, _ = make()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass


VOICES_JSON = [{"name": "Ava", "id": "voice-1"}, {"name": "Sam", "id": "voice-2"}]


def offering_options() -> tuple[TestClient, OverlayLink, EventBus]:
    client, link, bus = make()
    link.personalities = ["supportive", "protective"]
    link.voices = [VoiceOption.model_validate(voice) for voice in VOICES_JSON]
    return client, link, bus


def test_settings_state_on_connect_offers_personalities_and_voices() -> None:
    client, link, _ = offering_options()
    link.settings = Settings(proactive=False, personality="protective", voice_id="voice-2")
    with client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        state = socket.receive_json()
    assert state["type"] == "settings.state"
    assert state["personalities"] == ["supportive", "protective"]
    assert state["voices"] == VOICES_JSON
    assert state["settings"] == {
        "proactive": False,
        "personality": "protective",
        "voice_id": "voice-2",
    }


def test_settings_state_after_an_update_still_offers_them_and_shows_the_change() -> None:
    client, link, bus = offering_options()
    events = bus.subscribe()
    chosen = {"proactive": False, "personality": "protective", "voice_id": "voice-2"}
    with client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        socket.receive_json()
        socket.send_text(json.dumps({"type": "settings.update", "settings": chosen}))
        state = socket.receive_json()
    assert state["type"] == "settings.state"
    assert state["settings"] == chosen
    assert state["personalities"] == ["supportive", "protective"]
    assert state["voices"] == VOICES_JSON
    assert link.settings == Settings.model_validate(chosen)
    changes = [event for event in drain(events) if isinstance(event, SettingsChanged)]
    assert [change.settings for change in changes] == [Settings.model_validate(chosen)]


def test_settings_state_with_nothing_to_offer_sends_empty_lists() -> None:
    client, _, _ = make()
    with client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        state = socket.receive_json()
    assert state["personalities"] == [] and state["voices"] == []
