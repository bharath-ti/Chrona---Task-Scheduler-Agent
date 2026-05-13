"""M5 — Google Calendar scheduling (find_and_book_slot, etc.)."""

from __future__ import annotations

from typing import Any


def find_next_free_slot(task: dict[str, Any]) -> str | None:
    """
    Returns a human-readable string of the next free slot for this task.
    Used by M4 to show proposed slot in Slack.

    Stub until calendar integration is implemented — returns None so M4
    shows the 'no free slot' fallback text.
    """
    return None


def find_and_book_slot(task: dict[str, Any]) -> dict | None:
    """Placeholder for M5; not implemented yet."""
    print("[ERROR][m5_scheduler] find_and_book_slot is not implemented yet")
    return None
