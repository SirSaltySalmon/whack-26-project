"""Words for the "memory updated" notice."""

from brain.memory.models import RememberResult
from shared.protocol.messages import MemoryToast

MAX_TOAST_CHARS = 90


def toast_for(result: RememberResult) -> MemoryToast | None:
    """Shows real changes only. Repeated confirmations would make toasts noise, and conflicts and
    unsure facts reach the player as questions instead."""
    labels = {"stored": "Remembered", "replaced": "Updated"}
    label = labels.get(result.outcome)
    if label is None:
        return None
    if result.fact is not None:
        fact = result.fact
        text = f"{label}: {fact.subject} {fact.attribute}: {fact.value}"
        return MemoryToast(text=text[:MAX_TOAST_CHARS], source=fact.source)
    if result.closed:
        fact = result.closed[0]
        text = f"Forgot: {fact.subject} {fact.attribute}: {fact.value}"
        return MemoryToast(text=text[:MAX_TOAST_CHARS], source=fact.source)
    return None
