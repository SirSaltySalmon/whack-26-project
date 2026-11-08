"""Numbers as games print them, such as "72/100" or "1,250". Shared by the observer and readers."""

import re

_FRACTION = re.compile(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_fraction(text: str) -> tuple[int, int] | None:
    """Current and maximum, or None if there's no sensible pair. Current can't exceed maximum."""
    match = _FRACTION.search(text)
    if not match:
        return None
    current = int(match.group(1).replace(",", ""))
    maximum = int(match.group(2).replace(",", ""))
    if maximum <= 0 or current > maximum:
        return None
    return current, maximum


def first_number(text: str) -> float | None:
    match = _NUMBER.search(text)
    return float(match.group(0).replace(",", "")) if match else None
