"""WP3 end to end, through the real wiring in brain/app.py: record a live run, then replay it.

The live run uses a fake screen and talker, so nothing here needs a game, mic, keys or network.
"""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from brain.app import run
from brain.config import Settings
from brain.events import EventBus, GameEvent
from brain.perception.coords import CropRegion
from brain.replay.compare import compare, load_messages
from brain.replay.format import (
    EVENTS,
    FRAMES,
    MESSAGES,
    PARTNER_SAID,
    EventRecord,
    FrameRecord,
    read_jsonl,
    read_manifest,
)
from brain.tests.fakes import FakeTextLLM

LINE = "Whoa, that slime looks nasty."
REGION = CropRegion(10, 20, 200, 100)


class _Screen:
    """A whole monitor. The live wiring crops it to the game window's region."""

    def start(self) -> None:
        return None

    def grab(self) -> np.ndarray:
        screen = np.zeros((300, 400, 3), dtype=np.uint8)
        screen[20:120, 10:210] = (40, 80, 200)  # The game window, in a colour of its own
        return screen

    def stop(self) -> None:
        return None


class _Window:
    def __init__(self, _process: str) -> None:
        pass

    def visible_region(self) -> CropRegion:
        return REGION


def _settings(tmp_path: Path) -> Settings:
    # Every key is set to None outright, so a developer's environment can't reach a provider.
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        gemini_api_key=None,
        anthropic_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        exa_api_key=None,
        cartesia_api_key=None,
        # Keep a running dashboard from connecting to the test brain.
        brain_port=0,
        game_process="FakeGame",
        game_title="Test Game",
        capture_fps=20,
        record_fps=20,
        db_path=tmp_path / "brain.sqlite3",
        vault_dir=tmp_path / "vault",
        sessions_dir=tmp_path / "sessions",
        replay_snapshot=tmp_path / "no-snapshot.sql",
        replay_exit_grace_s=0.5,
    )


def _stub_server(monkeypatch: pytest.MonkeyPatch) -> None:
    async def idle_serve() -> None:
        await asyncio.Event().wait()

    # Stands in for uvicorn, so no socket opens.
    monkeypatch.setattr("brain.app.uvicorn.Server", lambda _: SimpleNamespace(serve=idle_serve))


async def _until(check: Callable[[], bool], timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting")
        await asyncio.sleep(0.05)


def _partner_lines(session: Path) -> list[str]:
    records = read_jsonl(session / EVENTS, EventRecord)
    return [record.data["text"] for record in records if record.kind == PARTNER_SAID]


async def _record_live_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = _settings(tmp_path)
    _stub_server(monkeypatch)
    monkeypatch.setattr("brain.app.default_live_source", _Screen)
    monkeypatch.setattr("brain.app.create_game_window", _Window)
    # Frames from _Screen are already in the overlay's units, on any OS.
    monkeypatch.setattr("brain.app.live_frame_scale", lambda: None)
    monkeypatch.setattr("brain.app.make_talker", lambda _factory: FakeTextLLM([LINE]))

    async def fake_typing(bus: EventBus) -> None:
        # The typed-turn hook is the one place a test can reach the run's bus.
        await asyncio.sleep(0.5)
        bus.publish(GameEvent("danger_started", {"level": "high", "threats": ["Slime"]}))

    monkeypatch.setattr("brain.app.typed_turns", fake_typing)
    brain = asyncio.create_task(run(settings, typed=True, record=True))
    sessions = settings.sessions_dir
    try:
        await _until(lambda: sessions.exists() and any(sessions.iterdir()))
        session = next(sessions.iterdir())
        await _until(lambda: LINE in _partner_lines(session))
        await asyncio.sleep(0.3)  # A few more frames after the line
    finally:
        brain.cancel()
        await asyncio.gather(brain, return_exceptions=True)
    return session


async def _replay(tmp_path: Path, session: Path, out: Path, **kwargs: Any) -> None:
    settings = _settings(tmp_path)
    await asyncio.wait_for(
        run(settings, replay_dir=session, exit_when_done=True, write_messages=out, **kwargs),
        timeout=30,
    )


async def test_a_recorded_live_run_replays_the_same_way_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await _record_live_session(tmp_path, monkeypatch)

    manifest = read_manifest(session)
    assert manifest.complete and manifest.game == "Test Game" and manifest.settings is not None
    frames = read_jsonl(session / FRAMES, FrameRecord)
    assert frames and all(frame.region is not None for frame in frames)
    assert frames[0].region is not None and frames[0].region.to_region() == REGION
    kinds = [record.kind for record in read_jsonl(session / EVENTS, EventRecord)]
    assert "GameEvent" in kinds and PARTNER_SAID in kinds

    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    await _replay(tmp_path, session, first, speed=2.0)
    await _replay(tmp_path, session, second, speed=2.0)

    replayed = load_messages(first)
    assert compare(replayed, load_messages(second)) == []
    # The replay says what the live run said, from the recording rather than a model.
    assert compare(load_messages(session / MESSAGES), replayed) == []
    assert any(message.get("text") == LINE for message in replayed)


async def test_a_missing_session_still_exits_when_done(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    await _replay(tmp_path, tmp_path / "no-such-session", out)
    assert load_messages(out) == []


def _main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> list[dict[str, Any]]:
    import brain.__main__ as entry_point

    calls: list[dict[str, Any]] = []

    async def fake_run(_settings: object, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(entry_point, "run", fake_run)
    # Real settings, but never the developer's .env.
    monkeypatch.setattr(entry_point, "Settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    monkeypatch.setattr("brain.game_setup.pick_game", lambda settings: (settings, ""))
    monkeypatch.setattr(entry_point, "configure_logging", lambda *_: None)
    monkeypatch.setattr("sys.argv", ["brain", *argv])
    entry_point.main()
    return calls


def test_replay_flags_reach_run(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = ["--replay", "s", "--speed", "4", "--exit-when-done", "--write-messages", "out.jsonl"]
    [call] = _main(monkeypatch, argv)
    assert call["replay_dir"] == Path("s") and call["speed"] == 4.0
    assert call["exit_when_done"] and call["write_messages"] == Path("out.jsonl")
    assert not call["record"]


def test_record_reaches_run_only_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    assert [call["record"] for call in _main(monkeypatch, ["--live", "--record"])] == [True]
    assert [call["record"] for call in _main(monkeypatch, ["--live"])] == [False]


@pytest.mark.parametrize(
    "argv",
    [
        ["--replay", "s", "--record"],
        ["--live", "--speed", "2"],
        ["--live", "--exit-when-done"],
        ["--live", "--write-messages", "out.jsonl"],
        ["--replay", "s", "--speed", "0"],
    ],
)
def test_flags_that_dont_fit_the_mode_are_refused(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _main(monkeypatch, argv)
    assert exit_info.value.code == 2
