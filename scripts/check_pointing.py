"""Evaluate pointing with one vision request per label.

Usage: python scripts/check_pointing.py labels.json
Use full-screen screenshots. Image paths are relative to the JSON file and points
are [x, y] pixels measured from the top left of each original screenshot.
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
from pydantic import BaseModel, Field, TypeAdapter  # noqa: E402

from brain.agent.handlers import POINT_MAX_EDGE_PX, VISION_MAX_TOKENS  # noqa: E402
from brain.agent.schemas import POINT_PROMPT, PointReply  # noqa: E402
from brain.capture.ring_buffer import Frame  # noqa: E402
from brain.config import Settings  # noqa: E402
from brain.llm.factory import LLMFactory  # noqa: E402
from brain.perception.closeup import Closeup, make_closeup  # noqa: E402
from brain.perception.coords import box_to_physical_rect, pixel_box_to_normalized  # noqa: E402


class Label(BaseModel):
    image: Path
    target: str = Field(min_length=1)
    point: tuple[int, int]


def load_labels(path: Path) -> list[Label]:
    labels = TypeAdapter(list[Label]).validate_json(path.read_bytes())
    if not labels:
        raise ValueError("No labels in the input file")
    for label in labels:
        label.image = path.parent / label.image
    return labels


def prepare(label: Label, edge: int) -> Closeup:
    image = cv2.imread(str(label.image))
    if image is None:
        raise ValueError(f"Could not read {label.image}")
    height, width = image.shape[:2]
    x, y = label.point
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"{label.point} outside {width} x {height} screenshot {label.image}")
    return make_closeup(Frame(0, image), 1, 0, edge)


def hits(reply: PointReply, image: Closeup, point: tuple[int, int]) -> bool:
    if not reply.found:
        return False
    try:
        box = pixel_box_to_normalized(reply.box_px, image.width, image.height)
    except ValueError:
        return False
    rect = box_to_physical_rect(box, image.region)
    x, y = point
    return rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height


async def main(path: Path) -> None:
    labels = load_labels(path)
    settings = Settings()
    vision = LLMFactory(settings).vision()
    edge = min(settings.closeup_max_edge_px, POINT_MAX_EDGE_PX)
    count = 0
    for label in labels:
        image = await asyncio.to_thread(prepare, label, edge)
        reply = await vision.vision_json(
            POINT_PROMPT.format(width=image.width, height=image.height, target=label.target),
            image.image,
            "image/jpeg",
            PointReply,
            VISION_MAX_TOKENS,
            detail="high",
        )
        hit = hits(reply, image, label.point)
        count += hit
        print(f"{'hit' if hit else 'miss'} | {label.image.name} | {label.target} | {reply.box_px}")
    print(f"Hit rate: {count}/{len(labels)} ({count / len(labels):.1%})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    asyncio.run(main(parser.parse_args().labels))
