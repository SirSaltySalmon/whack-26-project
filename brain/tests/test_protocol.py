from pathlib import Path

from scripts.gen_protocol import SCHEMA_PATH, render_schema
from shared.protocol import BrainMessageAdapter, OverlayMessageAdapter
from shared.protocol.messages import CardShow, OverlayRects


def test_messages_round_trip_by_type() -> None:
    sent = CardShow(card_id="a", title="Eye", body="Boss")
    assert isinstance(BrainMessageAdapter.validate_json(sent.model_dump_json()), CardShow)
    parsed = OverlayMessageAdapter.validate_json('{"type": "overlay.rects", "rects": []}')
    assert isinstance(parsed, OverlayRects)


def test_committed_schema_matches_models() -> None:
    assert Path(SCHEMA_PATH).read_text(encoding="utf-8") == render_schema(), (
        "Run: npm --prefix overlay run gen:protocol"
    )
