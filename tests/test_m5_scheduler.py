"""Unit tests for M5 slot helpers (no live Calendar API)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, time as dt_time
from unittest.mock import patch

import pytz

from modules import m5_scheduler


class TestM5MergeBusy(unittest.TestCase):
    def test_merge_overlapping_and_adjacent(self) -> None:
        tz = pytz.UTC
        a = datetime(2026, 5, 13, 9, 0, tzinfo=tz)
        b = datetime(2026, 5, 13, 10, 0, tzinfo=tz)
        c = datetime(2026, 5, 13, 9, 30, tzinfo=tz)
        d = datetime(2026, 5, 13, 11, 0, tzinfo=tz)
        merged = m5_scheduler._merge_busy([(a, b), (c, d)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0], (a, d))


@patch.dict(
    os.environ,
    {
        "TIMEZONE": "Asia/Kolkata",
        "WORKING_HOURS_START": "9",
        "WORKING_HOURS_END": "20",
    },
    clear=False,
)
class TestM5FindFreeSlot(unittest.TestCase):
    def test_finds_first_gap_same_day(self) -> None:
        tz = pytz.timezone("Asia/Kolkata")
        now = tz.localize(datetime(2026, 5, 13, 10, 0, 0))
        window_end = tz.localize(datetime(2026, 5, 20, 23, 0, 0))
        busy = [
            (
                tz.localize(datetime(2026, 5, 13, 11, 0, 0)),
                tz.localize(datetime(2026, 5, 13, 12, 0, 0)),
            )
        ]
        out = m5_scheduler._find_free_slot(
            busy, now, window_end, None, required_minutes=60, estimated_minutes=30
        )
        self.assertIsNotNone(out)
        slot_start, slot_end = out  # type: ignore[misc]
        self.assertEqual(slot_start, now)
        self.assertEqual(slot_end, now + timedelta(minutes=30))

    def test_no_gap_before_deadline(self) -> None:
        tz = pytz.timezone("Asia/Kolkata")
        now = tz.localize(datetime(2026, 5, 13, 10, 0, 0))
        deadline = tz.localize(datetime(2026, 5, 13, 10, 20, 0))
        window_end = deadline
        busy = []
        out = m5_scheduler._find_free_slot(
            busy, now, window_end, deadline, required_minutes=60, estimated_minutes=30
        )
        self.assertIsNone(out)


class TestM5FormatSlot(unittest.TestCase):
    @patch.dict(os.environ, {"TIMEZONE": "Asia/Kolkata"}, clear=False)
    def test_format_tomorrow_hint(self) -> None:
        tz = pytz.timezone("Asia/Kolkata")
        tomorrow = datetime.now(tz).date() + timedelta(days=1)
        s = tz.localize(datetime.combine(tomorrow, dt_time(9, 0)))
        e = s + timedelta(hours=2)
        label = m5_scheduler._format_slot_label(s, e)
        self.assertIn("tomorrow", label)
        self.assertIn("–", label)


if __name__ == "__main__":
    unittest.main()
