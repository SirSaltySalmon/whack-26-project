import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.control import ControlLink, ShutdownRequested, stop_when
from brain.director.rules import DirectorState, Say, decide
from brain.events import EventBus, SettingsChanged, VoicePreviewRequested
from brain.memory.browse import Browse
from brain.server import OverlayLink, create_app
from brain.tests.fakes import drain
from shared.protocol import PROTOCOL_VERSION
from shared.protocol.control import BrainStatus, FactView
from shared.protocol.messages import AvatarState, MemoryToast

FACT = FactView(
    id=1,
    subject="player",
    attribute="class",
    value="Summoner",
    source="player",
    confidence=0.9,
    tentative=False,
    valid_from=1.0,
)
STATUS = BrainStatus(
    mode="live",
    game_title="Some Game",
    session_id=3,
    watching=True,
    listening=False,
    speaking=False,
    talking=True,
    tools=True,
)


@dataclass
class Rig:
    client: TestClient
    link: OverlayLink
    control: ControlLink
    bus: EventBus
    browsed: list[tuple[str, bool, int]] = field(default_factory=list)
    stopped: list[bool] = field(default_factory=list)


def make(fail_browse: bool = False) -> Rig:
    bus = EventBus()
    link = OverlayLink(bus)
    link.personalities = ["supportive"]
    browsed: list[tuple[str, bool, int]] = []
    stopped: list[bool] = []

    async def browse(text: str, history: bool, limit: int) -> Browse:
        if fail_browse:
            raise RuntimeError("database is locked")
        browsed.append((text, history, limit))
        return Browse([FACT], [], [])

    async def recall(text: str) -> str:
        return f"Known: {text}"

    control = ControlLink(
        link,
        bus,
        browse=browse,
        recall=recall,
        status=lambda: STATUS,
        shutdown=lambda: stopped.append(True),
    )
    link.mirror = control.mirror
    client = TestClient(create_app(link, control))
    return Rig(client, link, control, bus, browsed, stopped)


def send(socket: Any, message: dict[str, Any]) -> None:
    socket.send_text(json.dumps(message))


def test_websites_are_refused() -> None:
    rig = make()
    with pytest.raises(WebSocketDisconnect):
        with rig.client.websocket_connect("/control", headers={"origin": "https://evil.example"}):
            pass


def test_hello_returns_settings_then_status() -> None:
    rig = make()
    with rig.client.websocket_connect("/control", headers={"origin": "file://"}) as socket:
        send(socket, {"type": "control.hello", "protocol_version": PROTOCOL_VERSION})
        state = socket.receive_json()
        status = socket.receive_json()
    assert state["type"] == "settings.state"
    assert state["personalities"] == ["supportive"]
    assert status["type"] == "brain.status"
    assert status["watching"] is True and status["session_id"] == 3


def test_memory_query_answers_by_request_id() -> None:
    rig = make()
    with rig.client.websocket_connect("/control") as socket:
        query = {"type": "memory.query", "request_id": "r1", "text": "class"}
        send(socket, {**query, "include_history": True})
        reply = socket.receive_json()
    assert reply["type"] == "memory.results"
    assert reply["request_id"] == "r1"
    assert reply["facts"][0]["value"] == "Summoner"
    assert reply["facts"][0]["source"] == "player"
    assert reply["elapsed_ms"] >= 0
    assert rig.browsed == [("class", True, 50)]


def test_context_preview_shows_what_the_talker_gets() -> None:
    rig = make()
    with rig.client.websocket_connect("/control") as socket:
        send(socket, {"type": "memory.context_preview", "request_id": "r2", "text": "boss"})
        reply = socket.receive_json()
    assert reply == {
        "type": "memory.context",
        "request_id": "r2",
        "context": "Known: boss",
        "elapsed_ms": reply["elapsed_ms"],
    }


def test_settings_from_the_control_center_reach_the_bus_and_come_back() -> None:
    rig = make()
    events = rig.bus.subscribe()
    settings = {
        "proactive": False,
        "personality": "supportive",
        "voice_id": "v1",
        "mic_enabled": False,
        "voice_style": "classic",
        "memory_search": "hybrid",
        "paused": False,
        "vision_enabled": False,
    }
    with rig.client.websocket_connect("/control") as socket:
        send(socket, {"type": "settings.update", "settings": settings})
        reply = socket.receive_json()
    assert reply["type"] == "settings.state"
    assert reply["settings"] == settings
    assert rig.link.settings.voice_id == "v1"
    assert any(isinstance(event, SettingsChanged) for event in drain(events))


class RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def test_memory_toasts_are_mirrored_but_other_overlay_messages_are_not() -> None:
    rig = make()
    socket = RecordingSocket()
    rig.control.attach(socket)  # type: ignore[arg-type]

    async def send_both() -> None:
        await rig.link.send(AvatarState(state="talking"))
        await rig.link.send(MemoryToast(text="Remembered your class", source="player"))

    asyncio.run(send_both())
    assert socket.sent == [
        {"type": "toast.memory", "text": "Remembered your class", "source": "player"}
    ]


def test_voice_preview_and_shutdown() -> None:
    rig = make()
    events = rig.bus.subscribe()
    with rig.client.websocket_connect("/control") as socket:
        send(socket, {"type": "voice.preview", "text": "This is how I sound."})
        send(socket, {"type": "control.shutdown"})
        # A request that answers proves both earlier messages were handled.
        send(socket, {"type": "memory.query", "request_id": "r3"})
        socket.receive_json()
    previews = [e for e in drain(events) if isinstance(e, VoicePreviewRequested)]
    assert [p.text for p in previews] == ["This is how I sound."]
    assert rig.stopped == [True]


def test_failures_reply_with_an_error_and_keep_the_socket() -> None:
    rig = make(fail_browse=True)
    with rig.client.websocket_connect("/control") as socket:
        socket.send_text("not json")
        invalid = socket.receive_json()
        send(socket, {"type": "memory.query", "request_id": "r4"})
        failed = socket.receive_json()
        send(socket, {"type": "memory.context_preview", "request_id": "r5", "text": "x"})
        still_open = socket.receive_json()
    assert invalid["type"] == "control.error" and invalid["request_id"] is None
    assert failed == {"type": "control.error", "request_id": "r4", "message": "RuntimeError"}
    assert still_open["request_id"] == "r5"


def test_voice_preview_is_a_plain_line() -> None:
    assert decide(VoicePreviewRequested(text="Hi"), DirectorState()) == [Say("Hi")]


def test_stop_when_ends_the_run() -> None:
    async def run() -> None:
        requested = asyncio.Event()
        requested.set()
        await stop_when(requested)

    with pytest.raises(ShutdownRequested):
        asyncio.run(run())
