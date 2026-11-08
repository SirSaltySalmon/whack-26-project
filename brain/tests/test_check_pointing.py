import pytest

from brain.agent.schemas import PointReply
from brain.perception.closeup import Closeup
from brain.perception.coords import CropRegion
from scripts.check_pointing import hits, load_labels


def test_label_paths_and_coordinates(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text('[{"image":"screen.png","target":"trash slot","point":[600,300]}]')
    (label,) = load_labels(path)
    assert label.image == tmp_path / "screen.png"
    assert label.point == (600, 300)
    path.write_text("[]")
    with pytest.raises(ValueError, match="No labels"):
        load_labels(path)


@pytest.mark.parametrize(
    "found, box, point, expected",
    [
        (True, [300, 150, 320, 180], (620, 330), True),
        (True, [300, 150, 320, 180], (310, 165), False),
        # A pixel past the edge is clipped, as pointing does live, so it still hits.
        (True, [-1, 150, 320, 180], (620, 330), True),
        # Far past the edge is refused, and a refused box counts as a miss.
        (True, [-200, 150, 320, 180], (620, 330), False),
        (False, [], (620, 330), False),
    ],
)
def test_score_in_original_screen_pixels(found, box, point, expected):
    image = Closeup(b"", CropRegion(0, 0, 2560, 1440), 1280, 720)
    assert hits(PointReply(found=found, label="slot", box_px=box), image, point) is expected
