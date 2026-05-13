"""Tests for M1->M2->M3->M4 orchestration (mocked M1/M2/M3/M4/disk reload)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import main


def _sample_email(
    *,
    mid: str = "m1",
    subject: str = "Hello",
    is_transcript: bool = False,
) -> dict:
    return {
        "message_id": mid,
        "subject": subject,
        "body": "Please do the thing.",
        "sender_email": "boss@example.com",
        "sender_name": "Boss",
        "sender_role": "manager",
        "sender_weight": 8,
        "timestamp": "2026-05-13T12:00:00+05:30",
        "is_transcript": is_transcript,
    }


def _sample_task(title: str = "Do the thing") -> dict:
    return {
        "title": title,
        "description": "Full context",
        "deadline": None,
        "estimated_minutes": 30,
        "urgency": "high",
        "raw_snippet": "Please do",
        "source": "email",
        "sender": "boss@example.com",
        "sender_name": "Boss",
        "sender_role": "manager",
        "sender_weight": 8,
    }


def _store_tasks(tasks: list) -> dict:
    return {"tasks": tasks, "last_cleared": None}


class TestPipelineM1M2M3M4(unittest.TestCase):
    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m1_empty_no_m2_m3_calls(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = []
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 0)
        self.assertEqual(out["task_count"], 0)
        self.assertEqual(out["items"], [])
        self.assertEqual(out["m3_stored_task_count"], 0)
        self.assertEqual(out["m4_approval_sent"], 0)
        self.assertEqual(out["m5_booked"], 0)
        mock_m2.assert_not_called()
        mock_m3.assert_called_once_with([])
        mock_send.assert_not_called()
        mock_timeout.assert_called_once()

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_one_email_tasks_passed_to_m3(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email()]
        mock_m2.return_value = [_sample_task("A"), _sample_task("B")]
        scored = [{"id": "1", "title": "A", "priority_score": 9.0}]
        mock_m3.return_value = scored
        mock_load.return_value = _store_tasks(scored)
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 1)
        self.assertEqual(out["task_count"], 2)
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(len(out["items"][0]["tasks"]), 2)
        mock_m2.assert_called_once()
        mock_m3.assert_called_once()
        passed = mock_m3.call_args[0][0]
        self.assertEqual(len(passed), 2)
        self.assertEqual({t["title"] for t in passed}, {"A", "B"})
        self.assertEqual(out["m3_stored_task_count"], 1)
        self.assertEqual(out["m3_tasks"][0]["id"], "1")
        mock_send.assert_not_called()

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_one_email_zero_tasks_m3_empty_input(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email(subject="FYI")]
        mock_m2.return_value = []
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["task_count"], 0)
        self.assertEqual(out["items"][0]["tasks"], [])
        mock_m3.assert_called_once_with([])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_multiple_emails_flatten_order_for_m3(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [
            _sample_email(mid="a", subject="S1"),
            _sample_email(mid="b", subject="S2"),
        ]

        def m2_side_effect(email: dict) -> list:
            if email["message_id"] == "a":
                return [_sample_task("Only A")]
            return []

        mock_m2.side_effect = m2_side_effect
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 2)
        self.assertEqual(out["task_count"], 1)
        self.assertEqual(mock_m2.call_count, 2)
        self.assertEqual(out["items"][0]["tasks"][0]["title"], "Only A")
        self.assertEqual(out["items"][1]["tasks"], [])
        mock_m3.assert_called_once_with([_sample_task("Only A")])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m2_raises_pipeline_continues_m3_runs(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [
            _sample_email(mid="x", subject="Bad"),
            _sample_email(mid="y", subject="Good"),
        ]
        mock_m2.side_effect = [
            RuntimeError("API down"),
            [_sample_task("Recovered")],
        ]
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 2)
        self.assertEqual(out["task_count"], 1)
        self.assertEqual(out["items"][0]["tasks"], [])
        self.assertEqual(len(out["items"][1]["tasks"]), 1)
        mock_m3.assert_called_once()

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m2_returns_non_list_coerced_to_empty(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email()]
        mock_m2.return_value = None  # type: ignore[assignment]
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["items"][0]["tasks"], [])
        mock_m3.assert_called_once_with([])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m1_raises_returns_empty_pipeline(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.side_effect = RuntimeError("Gmail down")
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 0)
        self.assertEqual(out["items"], [])
        mock_m2.assert_not_called()
        mock_m3.assert_called_once_with([])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m1_returns_non_list_coerced_to_empty(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = None  # type: ignore[assignment]
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["email_count"], 0)
        mock_m2.assert_not_called()
        mock_m3.assert_called_once_with([])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_transcript_flag_preserved_on_item(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email(is_transcript=True)]
        mock_m2.return_value = []
        mock_m3.return_value = []
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertTrue(out["items"][0]["is_transcript"])
        passed_email = mock_m2.call_args[0][0]
        self.assertTrue(passed_email["is_transcript"])

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m3_raises_empty_m3_tasks(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email()]
        mock_m2.return_value = [_sample_task()]
        mock_m3.side_effect = RuntimeError("store corrupt")
        mock_load.return_value = _store_tasks([])
        out = main.run_pipeline()
        self.assertEqual(out["m3_tasks"], [])
        self.assertEqual(out["m3_stored_task_count"], 0)

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m4_sends_for_extracted_needs_approval(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email()]
        mock_m2.return_value = [_sample_task()]
        scored = [
            {
                "id": "tid-1",
                "title": "VP asks ASAP",
                "needs_approval": True,
                "status": "extracted",
                "slack_message_ts": None,
                "sender_role": "VP",
            }
        ]
        mock_m3.return_value = scored
        mock_load.return_value = _store_tasks(scored)
        mock_send.return_value = True
        out = main.run_pipeline()
        mock_send.assert_called_once()
        self.assertEqual(out["m4_approval_sent"], 1)
        self.assertEqual(out["m4_approval_failed"], 0)
        mock_timeout.assert_called_once()

    @patch("utils.file_store.load_task_store")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m5_scheduler.find_and_book_slot", return_value=None)
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m4_skips_already_pending_or_slacked(
        self, mock_m1, mock_m5, mock_m2, mock_m3, mock_send, mock_timeout, mock_load
    ) -> None:
        mock_m1.return_value = [_sample_email()]
        mock_m2.return_value = [_sample_task()]
        scored = [
            {
                "id": "tid-2",
                "title": "Already sent",
                "needs_approval": True,
                "status": "pending_approval",
                "slack_message_ts": "123.456",
            }
        ]
        mock_m3.return_value = scored
        mock_load.return_value = _store_tasks(scored)
        out = main.run_pipeline()
        mock_send.assert_not_called()
        self.assertEqual(out["m4_approval_sent"], 0)


if __name__ == "__main__":
    unittest.main()
