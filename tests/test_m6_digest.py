"""Tests for M6 morning digest."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from modules import m6_digest


def _task(**kwargs: object) -> dict:
    base: dict = {
        "id": "1",
        "title": "T",
        "status": "scheduled",
        "urgency": "high",
        "sender_name": "A",
        "sender_role": "VP",
        "source": "email",
        "scheduled_start": "2026-05-14T09:00:00+05:30",
        "scheduled_end": "2026-05-14T10:00:00+05:30",
    }
    base.update(kwargs)  # type: ignore[arg-type]
    return base


class TestCategorizeTasks(unittest.TestCase):
    def test_scheduled_sorted_by_start(self) -> None:
        a = _task(id="a", scheduled_start="2026-05-14T11:00:00+05:30")
        b = _task(id="b", scheduled_start="2026-05-14T09:00:00+05:30")
        cats = m6_digest._categorize_tasks([a, b])
        self.assertEqual([t["id"] for t in cats["scheduled"]], ["b", "a"])

    def test_pending_extracted_needs_approval(self) -> None:
        t = _task(
            id="p",
            status="extracted",
            needs_approval=True,
            calendar_event_id=None,
        )
        cats = m6_digest._categorize_tasks([t])
        self.assertEqual(len(cats["pending"]), 1)

    def test_dismissed_bucket(self) -> None:
        t = _task(status="dismissed")
        cats = m6_digest._categorize_tasks([t])
        self.assertEqual(len(cats["dismissed"]), 1)


class TestBuildDigestBody(unittest.TestCase):
    @patch.dict(os.environ, {"YOUR_NAME": "TestUser"}, clear=False)
    def test_contains_sections(self) -> None:
        cats = {
            "scheduled": [_task(title="S1")],
            "pending": [],
            "unschedulable": [],
            "dismissed": [],
        }
        body = m6_digest._build_digest_body(cats, (1, 2, 3))
        self.assertIn("TestUser", body)
        self.assertIn("SCHEDULED TODAY (1 tasks)", body)
        self.assertIn("S1", body)
        self.assertIn("AUTO-DISMISSED (6 emails)", body)
        self.assertIn("1 newsletters, 2 notifications, 3 promotional", body)


@patch.dict(os.environ, {"YOUR_EMAIL": "u@example.com"}, clear=False)
class TestSendMorningDigest(unittest.TestCase):
    @patch.object(m6_digest.file_store, "save_task_store")
    @patch.object(m6_digest.gmail_client, "send_email", return_value=False)
    @patch.object(m6_digest.file_store, "load_task_store")
    def test_clears_store_when_send_fails(
        self, mock_load, mock_send, mock_save
    ) -> None:
        mock_load.return_value = {"tasks": [_task()], "last_cleared": None}
        ok = m6_digest.send_morning_digest()
        self.assertFalse(ok)
        mock_send.assert_called_once()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        self.assertEqual(saved["tasks"], [])
        self.assertIsNotNone(saved.get("last_cleared"))

    @patch.object(m6_digest.file_store, "save_task_store")
    @patch.object(m6_digest.gmail_client, "send_email", return_value=True)
    @patch.object(m6_digest.file_store, "load_task_store")
    def test_returns_true_when_send_ok(self, mock_load, mock_send, mock_save) -> None:
        mock_load.return_value = {"tasks": [], "last_cleared": None}
        self.assertTrue(m6_digest.send_morning_digest())
        mock_send.assert_called_once()
        mock_save.assert_called_once()


class TestNormalizeDigestTime(unittest.TestCase):
    def test_pad_and_bounds(self) -> None:
        import main

        self.assertEqual(main._normalize_digest_time("8:30"), "08:30")
        self.assertEqual(main._normalize_digest_time("23:59"), "23:59")
        self.assertEqual(main._normalize_digest_time("xx"), "08:00")


if __name__ == "__main__":
    unittest.main()
