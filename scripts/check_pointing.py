"""Tests the vision model's pointing (vision_model in config) on a real screenshot. One request.

Usage: python scripts/check_pointing.py <screenshot.png> "the player's health" [out.png]
Open the output image and check that the box lands on the target. Don't use a screenshot with
anything private on it: free-tier content is used to improve Google's products.
"""

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from brain.config import Settings  # noqa: E402
from brain.llm.base import PointTarget  # noqa: E402
from brain.llm.factory import LLMFactory  # noqa: E402
from brain.perception.coords import CropRegion, NormalizedBox, box_to_physical_rect  # noqa: E402

PROMPT = (
    "Locate this on the screenshot: {target}. Return label and box_2d as "
    "[ymin, xmin, ymax, xmax], each from 0 to 1000 relative to the image size."
)


async def main(path: Path, target: str, out: Path) -> None:
    settings = Settings()
    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"Could not read image: {path}")
    height, width = image.shape[:2]

    scale = min(1.0, settings.ai_image_max_edge_px / max(height, width))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".png", small)
    if not ok:
        raise SystemExit("Could not encode image")

    started = time.monotonic()
    result = (
        await LLMFactory(settings)
        .vision()
        .vision_json(
            PROMPT.format(target=target), encoded.tobytes(), "image/png", PointTarget, 2000
        )
    )
    seconds = time.monotonic() - started

    rect = box_to_physical_rect(NormalizedBox(*result.box_2d), CropRegion(0, 0, width, height))
    top_left = (int(rect.x), int(rect.y))
    bottom_right = (int(rect.x + rect.width), int(rect.y + rect.height))
    cv2.rectangle(image, top_left, bottom_right, (0, 255, 0), 3)
    cv2.imwrite(str(out), image)
    print(f"{result.label}: {result.box_2d} in {seconds:.2f}s. Saved {out}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("pointing_check.png")
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], output))
