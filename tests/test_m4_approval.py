"""Tests for M4 approval (mocked Slack / file_store)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from modules import m4_approval


def _task(**overrides: object) -> dict:
    base = {
        "id": "task-uuid-1",
        "title": "Ship the report",
        "description": "d",
        "deadline": None,
        "estimated_minutes": 60,
        "source": "email",
        "sources": ["email"],
        "sender": "vp@co.com",
        "sender_name": "VP",
        "sender_role": "VP",
        "sender_weight": 10,
        "urgency": "high",
        "raw_snippet": "Please ship",
        "priority_score": 8.0,
        "needs_approval": True,
        "status": "extracted",
        "calendar_event_id": None,
        "slack_message_ts": None,
        "seen_count": 1,
        "created_at": "2026-05-13T10:00:00+05:30",
        "updated_at": "2026-05-13T10:00:00+05:30",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


class TestBuildSlackBlocks(unittest.TestCase):
    def test_contains_header_and_actions(self) -> None:
        blocks = m4_approval._build_slack_blocks(_task(), "9:00 AM – 11:00 AM")
        self.assertEqual(blocks[0]["type"], "header")
        self.assertEqual(blocks[-1]["type"], "actions")
        ids = [e["action_id"] for e in blocks[-1]["elements"]]
        self.assertEqual(ids, ["approve_task", "edit_task_time", "dismiss_task"])


class TestSendApprovalRequest(unittest.TestCase):
    @patch.object(m4_approval.file_store, "update_task")
    @patch.object(m4_approval.slack_client, "send_dm")
    def test_demo_mode_approves_after_send(self, mock_send, mock_update) -> None:
        mock_send.return_value = {"ts": "1.2", "channel": "D123"}
        with patch.dict("os.environ", {"DEMO_MODE": "true", "SLACK_USER_ID": "U1"}, clear=False):
            ok = m4_approval.send_approval_request(_task(title="T1"))
        self.assertTrue(ok)
        mock_send.assert_called_once()
        mock_update.assert_called_once()
        args = mock_update.call_args[0]
        self.assertEqual(args[0], "task-uuid-1")
        self.assertEqual(args[1]["status"], "approved")

    @patch.object(m4_approval.file_store, "update_task")
    @patch.object(m4_approval.slack_client, "send_dm")
    def test_normal_mode_pending_after_send(self, mock_send, mock_update) -> None:
        mock_send.return_value = {"ts": "1.2", "channel": "D123"}
        with patch.dict("os.environ", {"DEMO_MODE": "false", "SLACK_USER_ID": "U1"}, clear=False):
            ok = m4_approval.send_approval_request(_task())
        self.assertTrue(ok)
        self.assertEqual(mock_update.call_args[0][1]["status"], "pending_approval")
        self.assertIn("pending_approval_at", mock_update.call_args[0][1])

    @patch.object(m4_approval.slack_client, "send_dm", return_value=None)
    @patch.object(m4_approval.file_store, "update_task")
    def test_send_failure_no_store_update(self, mock_update, _mock_send) -> None:
        with patch.dict("os.environ", {"SLACK_USER_ID": "U1"}, clear=False):
            ok = m4_approval.send_approval_request(_task())
        self.assertFalse(ok)
        mock_update.assert_not_called()


class TestHandlers(unittest.TestCase):
    @patch.object(m4_approval.file_store, "update_task")
    def test_handle_approve(self, mock_update) -> None:
        m4_approval.handle_approve("tid")
        mock_update.assert_called_once()
        self.assertEqual(mock_update.call_args[0][0], "tid")
        self.assertEqual(mock_update.call_args[0][1]["status"], "approved")

    @patch.object(m4_approval.file_store, "update_task")
    def test_handle_dismiss(self, mock_update) -> None:
        m4_approval.handle_dismiss("tid2")
        self.assertEqual(mock_update.call_args[0][1]["status"], "dismissed")


if __name__ == "__main__":
    unittest.main()
