from pathlib import Path

from scripts.gen_protocol import SCHEMA_PATH, render_schema
from shared.protocol import BrainMessageAdapter, OverlayMessageAdapter
from shared.protocol.messages import CardShow, DebugRegion, DebugRegions, OverlayRects, Rect


def test_messages_round_trip_by_type() -> None:
    sent = CardShow(card_id="a", title="Eye", body="Boss")
    assert isinstance(BrainMessageAdapter.validate_json(sent.model_dump_json()), CardShow)
    parsed = OverlayMessageAdapter.validate_json('{"type": "overlay.rects", "rects": []}')
    assert isinstance(parsed, OverlayRects)


def test_debug_regions_round_trip_and_an_empty_list_is_valid() -> None:
    sent = DebugRegions(
        regions=[
            DebugRegion(
                name="health",
                rect=Rect(x=1700, y=20, width=180, height=24),
                status="ok",
                display="72/100",
            ),
            DebugRegion(
                name="mana", rect=Rect(x=1880, y=60, width=20, height=200), status="masked"
            ),
        ]
    )
    parsed = BrainMessageAdapter.validate_json(sent.model_dump_json())
    assert parsed == sent
    assert isinstance(parsed, DebugRegions) and parsed.regions[1].display is None
    cleared = BrainMessageAdapter.validate_json('{"type": "debug.regions", "regions": []}')
    assert cleared == DebugRegions(regions=[])


def test_committed_schema_matches_models() -> None:
    assert Path(SCHEMA_PATH).read_text(encoding="utf-8") == render_schema(), (
        "Run: npm --prefix overlay run gen:protocol"
    )
