"""Saves what the learner checked a reader against, so a rejected reader can be looked at.

Only with --debug-regions, and only under sessions/, which stays out of git: the crops are
screen data. Each region gets its sample crops and a JSON note of what vision said about each.
"""

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import cv2

from brain.learner.validate import Sample

log = logging.getLogger(__name__)


def save_samples(
    folder: Path, region: str, samples: Sequence[Sample], accepted: bool, why: str
) -> None:
    """Blocking file writes: call it in a worker thread."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for index, sample in enumerate(samples):
            if sample.crop.size:
                cv2.imwrite(str(folder / f"{region}-{index}.png"), sample.crop)
        note = {
            "region": region,
            "accepted": accepted,
            "why": why,
            "expected": [sample.expected for sample in samples],
        }
        (folder / f"{region}.json").write_text(json.dumps(note, indent=2), encoding="utf-8")
        log.info("Saved %s's learning samples to %s", region, folder)
    except OSError:
        # Debug output only: the learner carries on without it.
        log.exception("Couldn't save %s's learning samples to %s", region, folder)
