"""Runs RapidOCR on one worker thread, so OCR never blocks the event loop or the colour readers.

Recognition alone (no text detection) reads a single line such as "72/100" in about 15 ms, while
detection adds about 850 ms. A reader's region is already cropped to its text, so numbers skip
detection. Only multi-line text needs it.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

OcrLine = tuple[str, float]


class OcrWorker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
        # Built on first use, inside the worker thread, so the engine only ever runs on one thread.
        self._engine: Any = None

    async def read(self, image: np.ndarray, detect: bool) -> list[OcrLine]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._read, image, detect)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _read(self, image: np.ndarray, detect: bool) -> list[OcrLine]:
        if self._engine is None:
            # Imported here because loading the models takes a moment and most runs never OCR.
            from rapidocr import RapidOCR

            self._engine = RapidOCR()
        result = self._engine(image, use_det=detect, use_cls=False)
        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        return [(str(text), float(score)) for text, score in zip(texts, scores, strict=False)]
