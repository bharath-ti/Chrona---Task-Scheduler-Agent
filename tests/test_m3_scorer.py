"""Unit tests for M3 scorer and file_store task APIs (mocked disk where needed)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from modules import m3_scorer
from utils import file_store


class TestWordOverlap(unittest.TestCase):
    def test_duplicate_high_overlap(self) -> None:
        a = "Complete the quarterly report"
        b = "complete quarterly report for Q3"
        self.assertGreater(m3_scorer._word_overlap(a, b), 0.70)

    def test_not_duplicate_at_threshold(self) -> None:
        a = "Send invoice"
        b = "Send welcome email"
        self.assertLessEqual(m3_scorer._word_overlap(a, b), 0.70)

    def test_empty_titles(self) -> None:
        self.assertEqual(m3_scorer._word_overlap("", "hello world"), 0.0)


class TestDedupAndScore(unittest.TestCase):
    def setUp(self) -> None:
        self._saved: dict | None = None

    def _capture_save(self, store: dict) -> None:
        self._saved = json.loads(json.dumps(store))

    def test_new_tasks_persisted_sorted(self) -> None:
        mem = {"tasks": [], "last_cleared": None}

        def fake_load() -> dict:
            return json.loads(json.dumps(mem))

        new_tasks = [
            {
                "title": "Low priority review",
                "description": "d",
                "deadline": None,
                "estimated_minutes": 30,
                "urgency": "low",
                "raw_snippet": "x",
                "source": "email",
                "sender": "p@e.com",
                "sender_name": "Peer",
                "sender_role": "peer",
                "sender_weight": 5,
            },
            {
                "title": "VP asks for deck ASAP",
                "description": "d2",
                "deadline": None,
                "estimated_minutes": 60,
                "urgency": "critical",
                "raw_snippet": "y",
                "source": "email",
                "sender": "vp@e.com",
                "sender_name": "VP",
                "sender_role": "VP",
                "sender_weight": 10,
            },
        ]
        with patch.object(file_store, "load_task_store", side_effect=fake_load):
            with patch.object(file_store, "save_task_store", side_effect=self._capture_save):
                out = m3_scorer.dedup_and_score(new_tasks)
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["priority_score"] >= out[1]["priority_score"])
        self.assertIsNotNone(self._saved)
        assert self._saved is not None
        self.assertEqual(len(self._saved["tasks"]), 2)

    def test_merge_duplicate_titles(self) -> None:
        mem = {
            "tasks": [
                {
                    "id": "existing-1",
                    "title": "Finish the project plan",
                    "description": "old",
                    "deadline": None,
                    "estimated_minutes": 60,
                    "source": "email",
                    "sources": ["email"],
                    "sender": "a@b.com",
                    "sender_name": "A",
                    "sender_role": "peer",
                    "sender_weight": 5,
                    "urgency": "medium",
                    "raw_snippet": "r",
                    "priority_score": 1.0,
                    "needs_approval": False,
                    "status": "extracted",
                    "calendar_event_id": None,
                    "slack_message_ts": None,
                    "seen_count": 1,
                    "created_at": "2026-01-01T00:00:00+05:30",
                    "updated_at": "2026-01-01T00:00:00+05:30",
                }
            ],
            "last_cleared": None,
        }

        def fake_load() -> dict:
            return json.loads(json.dumps(mem))

        new_tasks = [
            {
                "title": "finish project plan document",
                "description": "new desc",
                "deadline": None,
                "estimated_minutes": 90,
                "urgency": "high",
                "raw_snippet": "r2",
                "source": "transcript",
                "sender": "a@b.com",
                "sender_name": "A",
                "sender_role": "peer",
                "sender_weight": 5,
            }
        ]
        with patch.object(file_store, "load_task_store", side_effect=fake_load):
            with patch.object(file_store, "save_task_store", side_effect=self._capture_save):
                out = m3_scorer.dedup_and_score(new_tasks)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "existing-1")
        self.assertEqual(out[0]["title"], "Finish the project plan")
        self.assertIn("email", out[0]["sources"])
        self.assertIn("transcript", out[0]["sources"])
        self.assertEqual(out[0]["seen_count"], 2)

    def test_merge_same_source_message_id_preserves_workflow_status(self) -> None:
        """Re-extracted task from same Gmail id merges into existing row without reset."""
        mem = {
            "tasks": [
                {
                    "id": "existing-msg",
                    "source_message_id": "gmail-msg-42",
                    "title": "Finish the project plan",
                    "description": "old",
                    "deadline": None,
                    "estimated_minutes": 60,
                    "source": "email",
                    "sources": ["email"],
                    "sender": "a@b.com",
                    "sender_name": "A",
                    "sender_role": "peer",
                    "sender_weight": 5,
                    "urgency": "medium",
                    "raw_snippet": "r",
                    "priority_score": 1.0,
                    "needs_approval": True,
                    "status": "pending_approval",
                    "slack_message_ts": "99.88",
                    "calendar_event_id": None,
                    "seen_count": 1,
                    "created_at": "2026-01-01T00:00:00+05:30",
                    "updated_at": "2026-01-01T00:00:00+05:30",
                }
            ],
            "last_cleared": None,
        }

        def fake_load() -> dict:
            return json.loads(json.dumps(mem))

        new_tasks = [
            {
                "title": "finish project plan document",
                "description": "from LLM again",
                "deadline": None,
                "estimated_minutes": 90,
                "urgency": "high",
                "raw_snippet": "r2",
                "source": "email",
                "source_message_id": "gmail-msg-42",
                "sender": "a@b.com",
                "sender_name": "A",
                "sender_role": "peer",
                "sender_weight": 5,
            }
        ]
        with patch.object(file_store, "load_task_store", side_effect=fake_load):
            with patch.object(file_store, "save_task_store"):
                out = m3_scorer.dedup_and_score(new_tasks)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "existing-msg")
        self.assertEqual(out[0]["status"], "pending_approval")
        self.assertEqual(out[0]["slack_message_ts"], "99.88")
        self.assertEqual(out[0]["source_message_id"], "gmail-msg-42")

    def test_vp_needs_approval_despite_low_score_math(self) -> None:
        """Role VP forces needs_approval per spec."""
        mem = {"tasks": [], "last_cleared": None}

        def fake_load() -> dict:
            return json.loads(json.dumps(mem))

        new_tasks = [
            {
                "title": "Trivial VP ping",
                "description": "d",
                "deadline": None,
                "estimated_minutes": 15,
                "urgency": "low",
                "raw_snippet": "x",
                "source": "email",
                "sender": "v@e.com",
                "sender_name": "V",
                "sender_role": "VP",
                "sender_weight": 10,
            }
        ]
        with patch.object(file_store, "load_task_store", side_effect=fake_load):
            with patch.object(file_store, "save_task_store", side_effect=self._capture_save):
                out = m3_scorer.dedup_and_score(new_tasks)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["needs_approval"])


class TestFileStoreTaskPaths(unittest.TestCase):
    def test_roundtrip_task_store(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(file_store, "TASK_STORE_PATH", tmp_path / "task_store.json"):
                    a = file_store.load_task_store()
                    self.assertEqual(a["tasks"], [])
                    file_store.save_task_store(
                        {
                            "tasks": [
                                {
                                    "id": "t1",
                                    "title": "One",
                                    "status": "extracted",
                                }
                            ],
                            "last_cleared": "2026-05-01T08:00:00+05:30",
                        }
                    )
                    b = file_store.load_task_store()
                    self.assertEqual(len(b["tasks"]), 1)
                    self.assertEqual(file_store.get_task("t1"), b["tasks"][0])
                    self.assertIsNone(file_store.get_task("missing"))
                    file_store.update_task("t1", {"title": "Updated", "status": "approved"})
                    c = file_store.get_task("t1")
                    assert c is not None
                    self.assertEqual(c["title"], "Updated")
                    self.assertEqual(c["status"], "approved")


if __name__ == "__main__":
    unittest.main()
