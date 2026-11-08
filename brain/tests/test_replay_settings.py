"""Replayed sessions bring back the player's settings, from the manifest and from events."""

from pathlib import Path

from brain.events import SettingsChanged
from brain.tests.replay_rig import RigSession, event, write_session
from brain.tests.test_replay import replay
from shared.protocol.messages import Pacing


async def test_scale_and_settings_come_from_the_manifest(tmp_path: Path) -> None:
    settings = {
        "proactive": False,
        "personality": "snarky",
        "voice_id": "v2",
        "voice_style": "classic",
        "mic_enabled": True,
        "no_headphones": False,
        "memory_search": "semantic",
        "pacing": Pacing(advice_gap_s=0.0).model_dump(),
        "paused": False,
        "vision_enabled": True,
    }
    session = RigSession(display_scale=1.5, settings=settings)
    _, _, link = await replay(write_session(tmp_path, session))

    assert (link.display_scale, link.pinned_display_scale) == (1.5, 1.5)
    assert link.settings.model_dump() == {**settings, "custom_instructions": ""}


async def test_invalid_manifest_settings_keep_the_current_ones(tmp_path: Path) -> None:
    session = RigSession(settings={"proactive": "now and then"})
    _, _, link = await replay(write_session(tmp_path, session))

    assert link.settings.proactive is True


async def test_a_replayed_settings_change_updates_the_link(tmp_path: Path) -> None:
    changed = {"proactive": True, "personality": "calm", "voice_id": None}
    session = RigSession(events=[event(1.0, "SettingsChanged", settings=changed)])
    _, events, link = await replay(write_session(tmp_path, session))

    assert link.settings.personality == "calm"
    assert [type(e) for e in events] == [SettingsChanged]
