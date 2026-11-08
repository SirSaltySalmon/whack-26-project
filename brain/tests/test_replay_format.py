import dataclasses
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from brain.events import (
    CardClosedByPlayer,
    CardPageChanged,
    Event,
    GameEvent,
    OverlayConnected,
    PlayerMood,
    PlayerSpeech,
    PlayerSpeechPartial,
    PlayerStartedSpeaking,
    ProfileUpdated,
    QuestionAnswered,
    ReadersFailing,
    SettingsChanged,
    Tick,
)
from brain.perception.coords import CropRegion
from brain.replay.format import (
    PARTNER_SAID,
    SOURCE_REPLAY,
    EventRecord,
    Manifest,
    MessageRecord,
    RegionRecord,
    decode_frame,
    encode_frame,
    event_record,
    frame_file,
    jsonl_line,
    partner_said_record,
    read_jsonl,
    read_manifest,
    replay_event,
    session_dir_name,
    write_manifest,
)
from shared.protocol.messages import Settings

REPLAYED_AS_RECORDED: list[Event] = [
    PlayerStartedSpeaking(ts=1.0),
    PlayerSpeech("what's that?", ts=1.0),
    PlayerSpeechPartial("what's", ts=1.0),
    PlayerMood("frustrated", -0.6, 0.8, ts=1.0),
    QuestionAnswered("q1", "yes", ts=1.0),
    CardClosedByPlayer("card-1", ts=1.0),
    CardPageChanged("wiki", "https://terraria.wiki.gg/wiki/Slime", "Slime", ts=1.0),
]


def through_disk(record: EventRecord) -> EventRecord:
    """The record as replay reads it back, after a trip through a JSONL line."""
    return EventRecord.model_validate_json(jsonl_line(record))


@pytest.mark.parametrize("event", REPLAYED_AS_RECORDED, ids=lambda e: type(e).__name__)
def test_recorded_events_replay_as_themselves(event: Event) -> None:
    record = event_record(event, 2.5)
    assert record is not None and record.t == 2.5 and record.kind == type(event).__name__
    replayed = replay_event(through_disk(record))
    assert replayed is not None
    # Replay stamps its own time, so only the fields are compared.
    assert replayed == dataclasses.replace(event, ts=replayed.ts)


def test_an_observer_event_replays_with_the_replay_source() -> None:
    event = GameEvent("danger_started", {"level": "high", "threats": ("Slime",)}, ts=1.0)
    record = event_record(event, 3.0)
    assert record is not None
    assert record.data == {
        "name": "danger_started",
        "data": {"level": "high", "threats": ["Slime"]},
        "source": "observer",
    }
    replayed = replay_event(through_disk(record))
    assert isinstance(replayed, GameEvent)
    assert replayed.source == SOURCE_REPLAY
    assert (replayed.name, replayed.data) == (
        "danger_started",
        {"level": "high", "threats": ["Slime"]},
    )


def test_reader_events_are_recorded_but_not_replayed() -> None:
    record = event_record(GameEvent("hp_low", {"value": 20}, source="reader"), 1.0)
    assert record is not None and record.data["source"] == "reader"
    assert replay_event(record) is None


def test_partner_lines_are_recorded_but_not_replayed_on_the_bus() -> None:
    record = partner_said_record("That looks rough.", 4.0)
    assert (record.kind, record.data) == (PARTNER_SAID, {"text": "That looks rough."})
    assert replay_event(record) is None


@pytest.mark.parametrize(
    "event",
    [
        OverlayConnected(1.5),
        ProfileUpdated("Terraria"),
        ReadersFailing("Terraria", ("hp",)),
        Tick(),
    ],
    ids=lambda e: type(e).__name__,
)
def test_unrecorded_events_have_no_record(event: Event) -> None:
    assert event_record(event, 1.0) is None


def test_a_settings_change_round_trips() -> None:
    settings = Settings(proactive=False, personality="snarky", voice_id="v1")
    record = event_record(SettingsChanged(settings), 5.0)
    assert record is not None
    replayed = replay_event(through_disk(record))
    assert isinstance(replayed, SettingsChanged) and replayed.settings == settings


@pytest.mark.parametrize(
    "record",
    [
        EventRecord(t=1.0, kind="PlayerSpeech", data={}),
        EventRecord(t=1.0, kind="PlayerSpeech", data={"transcript": "hi", "extra": 1}),
        EventRecord(t=1.0, kind="SettingsChanged", data={}),
        EventRecord(t=1.0, kind="SettingsChanged", data={"settings": {"proactive": "maybe"}}),
        EventRecord(t=1.0, kind="NotAnEvent", data={}),
    ],
)
def test_a_record_that_doesnt_fit_is_skipped(record: EventRecord) -> None:
    assert replay_event(record) is None


def test_read_jsonl_skips_bad_lines_and_a_cut_short_last_line(tmp_path: Path) -> None:
    path = tmp_path / "messages.jsonl"
    good = [
        MessageRecord(t=1.0, message={"type": "pointer.hide"}),
        MessageRecord(t=2.0, message={}),
    ]
    path.write_text(
        jsonl_line(good[0]) + "not json\n\n" + jsonl_line(good[1]) + '{"t": 3.0, "mess',
        encoding="utf-8",
    )
    assert read_jsonl(path, MessageRecord) == good


def test_read_jsonl_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "missing.jsonl", EventRecord) == []


def test_frames_survive_encoding() -> None:
    ramp = np.linspace(0, 255, 64, dtype=np.uint8)
    image = np.stack(
        [np.tile(ramp, (36, 1)), np.full((36, 64), 40, np.uint8), np.tile(ramp, (36, 1))[::-1]],
        axis=2,
    )
    decoded = decode_frame(encode_frame(image))
    assert decoded.shape == image.shape
    assert np.abs(decoded.astype(int) - image.astype(int)).max() <= 8


def test_decoding_garbage_raises() -> None:
    with pytest.raises(ValueError):
        decode_frame(b"not a jpeg")


@pytest.mark.parametrize(
    ("game", "slug"),
    [
        ("Terraria", "terraria"),
        ("The Legend of Zelda: Breath of the Wild!", "the-legend-of-zelda-breath-of-the-wild"),
        ("  Hollow   Knight  ", "hollow-knight"),
        ("Pokémon", "pok-mon"),
        ("", "game"),
        ("???", "game"),
    ],
)
def test_session_names_slug_the_title(game: str, slug: str) -> None:
    assert session_dir_name(game, datetime(2026, 11, 8, 1, 23, 45)) == f"20261108-012345-{slug}"


def test_frame_files_are_numbered_in_the_frames_folder() -> None:
    assert frame_file(12) == "frames/000012.jpg"


def test_regions_round_trip() -> None:
    region = CropRegion(10, 20, 1920, 1080)
    record = RegionRecord.of(region)
    assert record is not None and record.to_region() == region
    assert RegionRecord.of(None) is None


def test_manifests_round_trip_and_leave_no_temporary_file(tmp_path: Path) -> None:
    manifest = Manifest(
        game="Terraria",
        created_at="2026-11-08T01:23:45",
        display_scale=1.5,
        record_fps=5,
        settings=Settings().model_dump(mode="json"),
    )
    write_manifest(tmp_path, manifest)
    finished = manifest.model_copy(update={"complete": True, "duration_s": 12.5})
    write_manifest(tmp_path, finished)
    assert read_manifest(tmp_path) == finished
    assert [p.name for p in tmp_path.iterdir()] == ["manifest.json"]


def test_a_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_manifest(tmp_path)
