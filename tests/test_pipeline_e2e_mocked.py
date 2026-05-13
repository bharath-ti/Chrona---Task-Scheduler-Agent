"""End-to-end pipeline tests: M1->M2->M3->M4->M5 order and wiring (all mocked)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import schedule

import main


def _email(mid: str = "e1") -> dict:
    return {
        "message_id": mid,
        "subject": "Action needed",
        "body": "Please complete the report.",
        "sender_email": "vp@example.com",
        "sender_name": "VP",
        "sender_role": "VP",
        "sender_weight": 10,
        "timestamp": "2026-05-13T12:00:00+05:30",
        "is_transcript": False,
    }


def _task(title: str) -> dict:
    return {
        "title": title,
        "description": "d",
        "deadline": None,
        "estimated_minutes": 45,
        "urgency": "high",
        "raw_snippet": "snip",
        "source": "email",
        "sender": "vp@example.com",
        "sender_name": "VP",
        "sender_role": "VP",
        "sender_weight": 10,
    }


def _store(tasks: list) -> dict:
    return {"tasks": tasks, "last_cleared": None}


class TestPipelineFullChain(unittest.TestCase):
    """Verifies run_pipeline() touches M1 through M5 in the intended order."""

    @patch("utils.file_store.load_task_store")
    @patch("modules.m5_scheduler.find_and_book_slot")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m1_through_m5_call_order_with_email(
        self,
        mock_m1,
        mock_m2,
        mock_m3,
        mock_send,
        mock_timeout,
        mock_m5,
        mock_load,
    ) -> None:
        mock_m1.return_value = [_email()]
        mock_m2.return_value = [_task("From email")]
        scored = [
            {
                "id": "t-auto",
                "title": "From email",
                "status": "extracted",
                "needs_approval": False,
                "priority_score": 7.0,
                "calendar_event_id": None,
            }
        ]
        mock_m3.return_value = scored
        mock_m5.return_value = {"id": "cal-ev-1", "summary": "From email"}
        mock_load.return_value = _store(scored)

        out = main.run_pipeline()

        mock_m1.assert_called_once()
        mock_m2.assert_called_once()
        self.assertEqual(mock_m2.call_args[0][0]["message_id"], "e1")
        mock_m3.assert_called_once()
        self.assertEqual(len(mock_m3.call_args[0][0]), 1)
        mock_send.assert_not_called()
        mock_timeout.assert_called_once()
        mock_m5.assert_called_once()
        self.assertEqual(mock_m5.call_args[0][0]["id"], "t-auto")
        self.assertEqual(out["m5_booked"], 1)
        self.assertEqual(out["email_count"], 1)
        self.assertEqual(out["task_count"], 1)

    @patch("utils.file_store.load_task_store")
    @patch("modules.m5_scheduler.find_and_book_slot")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_m4_sends_before_m5_reads_store(
        self,
        mock_m1,
        mock_m2,
        mock_m3,
        mock_send,
        mock_timeout,
        mock_m5,
        mock_load,
    ) -> None:
        """M4 uses scored_tasks; M5 uses reload: approved tasks must appear in load_task_store."""
        mock_m1.return_value = [_email(mid="e2")]
        mock_m2.return_value = [_task("Needs VP")]
        extracted = {
            "id": "t-vp",
            "title": "Needs VP",
            "status": "extracted",
            "needs_approval": True,
            "slack_message_ts": None,
            "priority_score": 9.0,
            "calendar_event_id": None,
        }
        mock_m3.return_value = [extracted]
        mock_send.return_value = True
        mock_m5.return_value = None

        approved = {**extracted, "status": "approved", "slack_message_ts": "1.0"}
        mock_load.side_effect = [
            _store([approved]),
            _store([approved]),
        ]

        out = main.run_pipeline()

        mock_send.assert_called_once()
        self.assertEqual(out["m4_approval_sent"], 1)
        mock_m5.assert_called_once()
        self.assertEqual(mock_m5.call_args[0][0]["status"], "approved")

    @patch("utils.file_store.load_task_store")
    @patch("modules.m5_scheduler.find_and_book_slot")
    @patch("modules.m4_approval.check_pending_timeouts")
    @patch("modules.m4_approval.send_approval_request")
    @patch("modules.m3_scorer.dedup_and_score")
    @patch("modules.m2_extractor.extract_tasks")
    @patch("modules.m1_watcher.fetch_and_filter_emails")
    def test_summary_includes_m1_through_m5_keys(
        self,
        mock_m1,
        mock_m2,
        mock_m3,
        mock_send,
        mock_timeout,
        mock_m5,
        mock_load,
    ) -> None:
        mock_m1.return_value = []
        mock_m3.return_value = []
        mock_m5.return_value = None
        mock_load.return_value = _store([])
        out = main.run_pipeline()
        for key in (
            "email_count",
            "task_count",
            "items",
            "m3_stored_task_count",
            "m3_needs_approval_count",
            "m3_tasks",
            "m4_approval_sent",
            "m4_approval_failed",
            "m5_booked",
            "m5_skipped",
            "m5_errors",
        ):
            self.assertIn(key, out)


class TestDaemonEntrypoint(unittest.TestCase):
    def tearDown(self) -> None:
        schedule.clear()

    @patch("main.run_pipeline")
    @patch("time.sleep", side_effect=KeyboardInterrupt)
    @patch("schedule.run_pending")
    @patch("schedule.every")
    def test_run_daemon_loop_registers_job(
        self,
        mock_every,
        mock_run_pending,
        mock_sleep,
        mock_run_pipeline,
    ) -> None:
        import schedule

        minutes_chain = MagicMock()
        mock_every.return_value.minutes = minutes_chain
        minutes_chain.do.return_value = None

        with self.assertRaises(KeyboardInterrupt):
            main.run_daemon_loop(poll_minutes=3, run_immediately=False)

        mock_every.assert_called_once_with(3)
        minutes_chain.do.assert_called_once()
        mock_run_pipeline.assert_not_called()
        mock_run_pending.assert_called()


if __name__ == "__main__":
    unittest.main()
