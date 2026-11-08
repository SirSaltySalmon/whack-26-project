import json
import logging
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.events import (
    CardPageChanged,
    EventBus,
    OverlayConnected,
    PageContentReceived,
    SettingsChanged,
)
from brain.server import OverlayLink, create_app
from brain.tests.fakes import drain
from shared.protocol import PROTOCOL_VERSION, BrainMessage
from shared.protocol.messages import AvatarState, Settings, VoiceOption


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
        "mic_enabled": True,
        "voice_style": "expressive",
        "memory_search": "keyword",
    }


def test_settings_state_after_an_update_still_offers_them_and_shows_the_change() -> None:
    client, link, bus = offering_options()
    events = bus.subscribe()
    chosen = {
        "proactive": False,
        "personality": "protective",
        "voice_id": "voice-2",
        "mic_enabled": True,
        "voice_style": "classic",
        "memory_search": "hybrid",
    }
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


async def test_on_send_sees_messages_with_no_overlay_connected() -> None:
    _, link, _ = make()
    seen: list[BrainMessage] = []
    link.on_send = seen.append
    await link.send(AvatarState(state="talking"))
    assert seen == [AvatarState(state="talking")]


def test_a_failing_on_send_does_not_stop_the_overlay_getting_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, link, _ = make()

    def broken(message: BrainMessage) -> None:
        raise OSError("disk full")

    link.on_send = broken
    with client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        assert socket.receive_json()["type"] == "settings.state"
    assert "on_send hook failed for settings.state" in caplog.text


def test_a_pinned_scale_survives_the_overlay_reporting_another(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, link, bus = make()
    link.display_scale = link.pinned_display_scale = 1.25
    events = bus.subscribe()
    with caplog.at_level(logging.WARNING), client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        assert socket.receive_json()["type"] == "settings.state"
    assert link.display_scale == 1.25
    assert drain(events) == [OverlayConnected(display_scale=1.5, ts=ANY)]
    assert "1.5" in caplog.text and "1.25" in caplog.text


def test_without_a_pin_the_overlay_sets_the_scale_and_nothing_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, link, bus = make()
    events = bus.subscribe()
    with caplog.at_level(logging.WARNING), client.websocket_connect("/ws") as socket:
        socket.send_text(ready())
        socket.receive_json()
    assert link.display_scale == 1.5
    assert drain(events) == [OverlayConnected(display_scale=1.5, ts=ANY)]
    assert not [record for record in caplog.records if record.name == "brain.server"]


def test_frame_scale_override_wins_over_the_reported_scale() -> None:
    # mss on macOS captures in points, so a Retina overlay's 2.0 must not be applied to frames.
    client, link, _ = make()
    link.frame_scale_override = 1.0
    with client.websocket_connect("/ws", headers={"origin": "file://"}) as socket:
        socket.send_text(ready())
        socket.receive_json()
    assert link.reported_scale == 1.5
    assert link.display_scale == 1.0


def test_page_content_reaches_the_bus() -> None:
    client, _, bus = make()
    events = bus.subscribe()
    reply = {
        "type": "page.content",
        "request_id": "r1",
        "card_id": "wiki",
        "url": "https://wiki.example/wiki/A",
        "title": "A",
        "text": "Line one\nLine two",
        "visible_text": "Line two",
    }
    with client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps(reply))
        socket.send_text(ready())
        socket.receive_json()
    assert events.get_nowait() == PageContentReceived(
        request_id="r1",
        card_id="wiki",
        url="https://wiki.example/wiki/A",
        title="A",
        text="Line one\nLine two",
        visible_text="Line two",
        truncated=False,
        ts=ANY,
    )


class ClosingSocket:
    """Closed by the overlay just as the brain sends, as happened in a live run."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def send_text(self, _text: str) -> None:
        raise self.error


async def test_a_send_racing_the_overlay_closing_is_dropped_not_raised() -> None:
    from fastapi import WebSocketDisconnect

    from shared.protocol.messages import DebugRegions

    for error in (WebSocketDisconnect(code=1006), RuntimeError("close message has been sent")):
        link = OverlayLink(EventBus())
        link.attach(ClosingSocket(error))  # type: ignore[arg-type]
        await link.send(DebugRegions(regions=[]))
        assert not link.connected
        # And the next send is simply dropped, like any send with no overlay.
        await link.send(DebugRegions(regions=[]))
