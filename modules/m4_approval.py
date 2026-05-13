"""M4 — Slack DM approval gate for tasks that need human confirmation."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import pytz
from dotenv import load_dotenv

from modules import m5_scheduler
from utils import file_store
from utils import slack_client

APPROVAL_TIMEOUT_MINUTES = 30


def _is_demo_mode() -> bool:
    load_dotenv()
    return os.getenv("DEMO_MODE", "false").lower() == "true"


def _timezone() -> Any:
    load_dotenv()
    return pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))


def _now_iso() -> str:
    return datetime.now(_timezone()).isoformat()


def _parse_iso(dt_str: str) -> datetime | None:
    try:
        s = dt_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = _timezone().localize(dt)
        else:
            dt = dt.astimezone(_timezone())
        return dt
    except (ValueError, TypeError):
        return None


def _build_slack_blocks(task: dict, proposed_slot: str) -> list[dict]:
    """Builds and returns the Slack Block Kit blocks list for the approval message."""
    task_id = str(task.get("id", ""))
    title = str(task.get("title", "")) or "(no title)"
    sender_name = str(task.get("sender_name", ""))
    sender_role = str(task.get("sender_role", ""))
    from_line = f"{sender_name} ({sender_role})".strip()
    src = task.get("source")
    if not src and task.get("sources"):
        srcs = task.get("sources")
        if isinstance(srcs, list) and srcs:
            src = ", ".join(str(x) for x in srcs)
    source = str(src or "email")
    deadline = task.get("deadline")
    deadline_s = "Not specified" if deadline in (None, "", "null") else str(deadline)
    try:
        est = int(task.get("estimated_minutes", 0))
    except (TypeError, ValueError):
        est = 0
    est_s = f"{est} minutes" if est else "Not specified"

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "New high-priority task detected",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Title*\n{title}"},
                {"type": "mrkdwn", "text": f"*From*\n{from_line}"},
                {"type": "mrkdwn", "text": f"*Source*\n{source}"},
                {"type": "mrkdwn", "text": f"*Deadline*\n{deadline_s}"},
                {"type": "mrkdwn", "text": f"*Estimated time*\n{est_s}"},
                {"type": "mrkdwn", "text": f"*Proposed slot*\n{proposed_slot}"},
            ],
        },
        {
            "type": "actions",
            "block_id": f"actions_{task_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                    "style": "primary",
                    "action_id": "approve_task",
                    "value": task_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit time", "emoji": True},
                    "action_id": "edit_task_time",
                    "value": task_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Dismiss", "emoji": True},
                    "style": "danger",
                    "action_id": "dismiss_task",
                    "value": task_id,
                },
            ],
        },
    ]


def send_approval_request(task: dict) -> bool:
    """
    Sends a Slack DM to the user requesting approval for a task.

    Args:
        task: Full task dict from M3

    Returns:
        True if message sent successfully, False on error.

    Side effects:
        - Updates task status to "pending_approval" in task_store.json
        - Stores slack_message_ts (and slack_channel_id) on the task object
        - In DEMO_MODE: immediately sets status="approved" without waiting
    """
    try:
        load_dotenv()
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            print("[ERROR][M4] send_approval_request: task has no id")
            return False

        user_id = (os.getenv("SLACK_USER_ID") or "").strip()
        if not user_id:
            print("[ERROR][M4] SLACK_USER_ID is not set")
            return False

        proposed = m5_scheduler.find_next_free_slot(task)
        proposed_display = proposed or "No free slot found before deadline ⚠️"
        blocks = _build_slack_blocks(task, proposed_display)
        fallback = f"Approval needed: {task.get('title', '')}"

        sent = slack_client.send_dm(user_id, text=fallback, blocks=blocks)
        if not sent:
            return False

        ts = sent.get("ts")
        channel = sent.get("channel")
        demo = _is_demo_mode()

        if demo:
            file_store.update_task(
                task_id,
                {
                    "status": "approved",
                    "slack_message_ts": ts,
                    "slack_channel_id": channel,
                    "pending_approval_at": None,
                    "updated_at": _now_iso(),
                },
            )
            print(f"[M4] DEMO_MODE: auto-approving task: {task.get('title', '')}")
            return True

        file_store.update_task(
            task_id,
            {
                "status": "pending_approval",
                "slack_message_ts": ts,
                "slack_channel_id": channel,
                "pending_approval_at": _now_iso(),
                "updated_at": _now_iso(),
            },
        )
        return True
    except Exception as e:
        print(f"[ERROR][M4] send_approval_request failed: {e}")
        return False


def handle_approve(task_id: str) -> None:
    """Sets task status to 'approved' in task_store.json. Called by Slack webhook."""
    try:
        tid = str(task_id or "").strip()
        if not tid:
            print("[ERROR][M4] handle_approve: empty task_id")
            return
        file_store.update_task(
            tid,
            {
                "status": "approved",
                "updated_at": _now_iso(),
                "pending_approval_at": None,
            },
        )
    except Exception as e:
        print(f"[ERROR][M4] handle_approve failed: {e}")


def handle_dismiss(task_id: str) -> None:
    """Sets task status to 'dismissed' in task_store.json. Called by Slack webhook."""
    try:
        tid = str(task_id or "").strip()
        if not tid:
            print("[ERROR][M4] handle_dismiss: empty task_id")
            return
        file_store.update_task(
            tid,
            {
                "status": "dismissed",
                "updated_at": _now_iso(),
                "pending_approval_at": None,
            },
        )
    except Exception as e:
        print(f"[ERROR][M4] handle_dismiss failed: {e}")


def check_pending_timeouts() -> None:
    """
    Called by main.py every 5 minutes.
    For tasks with status="pending_approval" older than 30 minutes:
    - Keep status as "pending_approval" (do NOT auto-approve)
    - Add "timed_out": True to task
    - Log: print(f"[M4] Timeout: task {task['id']} will appear in digest as pending")
    """
    try:
        store = file_store.load_task_store()
        tasks = store.get("tasks", [])
        if not isinstance(tasks, list):
            return
        now = datetime.now(_timezone())
        cutoff = now - timedelta(minutes=APPROVAL_TIMEOUT_MINUTES)
        for t in tasks:
            if not isinstance(t, dict):
                continue
            if str(t.get("status")) != "pending_approval":
                continue
            if t.get("timed_out"):
                continue
            anchor = t.get("pending_approval_at") or t.get("updated_at")
            if not anchor:
                continue
            dt = _parse_iso(str(anchor))
            if dt is None:
                continue
            if dt <= cutoff:
                tid = str(t.get("id", ""))
                if not tid:
                    continue
                file_store.update_task(tid, {"timed_out": True, "updated_at": _now_iso()})
                print(f"[M4] Timeout: task {tid} will appear in digest as pending")
    except Exception as e:
        print(f"[ERROR][M4] check_pending_timeouts failed: {e}")
