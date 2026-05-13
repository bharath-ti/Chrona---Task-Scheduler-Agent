"""M6 — morning digest email and task_store reset."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pytz
from dotenv import load_dotenv

from utils import file_store
from utils import gmail_client

_SEP = "\n" + ("-" * 36) + "\n"


def _timezone() -> Any:
    load_dotenv()
    return pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))


def _now_iso() -> str:
    return datetime.now(_timezone()).isoformat()


def _parse_sort_key(task: dict[str, Any]) -> datetime:
    """Sort scheduled block by scheduled_start; missing values sort last."""
    raw = task.get("scheduled_start")
    if not raw:
        return datetime.max.replace(tzinfo=_timezone())
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = _timezone().localize(dt)
        else:
            dt = dt.astimezone(_timezone())
        return dt
    except (ValueError, TypeError):
        return datetime.max.replace(tzinfo=_timezone())


def _categorize_tasks(tasks: list[dict]) -> dict[str, list[dict]]:
    """
    Returns:
        scheduled, pending, unschedulable, dismissed lists (dict copies safe to clear after).
    """
    scheduled: list[dict] = []
    pending: list[dict] = []
    unschedulable: list[dict] = []
    dismissed: list[dict] = []

    for t in tasks:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status") or "")
        needs = bool(t.get("needs_approval"))
        has_cal = bool(t.get("calendar_event_id"))

        if st == "dismissed":
            dismissed.append(t)
        elif st == "unschedulable":
            unschedulable.append(t)
        elif st in ("scheduled", "auto_scheduled"):
            scheduled.append(t)
        elif st == "pending_approval" or (
            st == "extracted" and needs
        ) or (st == "approved" and not has_cal) or (
            st == "extracted" and not needs and not has_cal
        ):
            pending.append(t)

    scheduled.sort(key=_parse_sort_key)
    return {
        "scheduled": scheduled,
        "pending": pending,
        "unschedulable": unschedulable,
        "dismissed": dismissed,
    }


def _format_time_slot(task: dict[str, Any]) -> str:
    ss = task.get("scheduled_start")
    se = task.get("scheduled_end")
    if ss and se:
        return f"{ss} - {se}"
    if ss:
        return str(ss)
    return "Time TBD"


def _digest_date_line() -> str:
    return datetime.now(_timezone()).strftime("%Y-%m-%d")


def _build_digest_body(categories: dict[str, list[dict]], dismissed_email_count: tuple[int, int, int]) -> str:
    """Builds the full plain-text digest email body."""
    load_dotenv()
    name = os.getenv("YOUR_NAME", "there")
    n, m, k = dismissed_email_count
    auto_email_total = n + m + k

    sch = categories.get("scheduled") or []
    pend = categories.get("pending") or []
    uns = categories.get("unschedulable") or []
    dismissed_tasks = categories.get("dismissed") or []

    lines: list[str] = [
        f"Good morning {name} - here is what your agent did overnight.",
        "",
        _SEP.strip(),
        f"SCHEDULED TODAY ({len(sch)} tasks)",
        _SEP.strip(),
    ]

    for t in sch:
        urg = str(t.get("urgency") or "medium").upper()
        title = str(t.get("title") or "(no title)")
        slot = _format_time_slot(t)
        sn = str(t.get("sender_name") or "")
        sr = str(t.get("sender_role") or "")
        src = str(t.get("source") or "email")
        lines.append(f"[{urg}]  {title}")
        lines.append(f"         {slot}  -  from {sn} ({sr})")
        lines.append(f"         via {src}")
        lines.append("")

    if not sch:
        lines.append("(none)")
        lines.append("")

    lines.extend(
        [
            _SEP.strip(),
            f"NEEDS YOUR APPROVAL ({len(pend)} tasks)",
            _SEP.strip(),
        ]
    )
    for t in pend:
        title = str(t.get("title") or "(no title)")
        sn = str(t.get("sender_name") or "")
        dl = t.get("deadline") or "Not specified"
        lines.append(f"- {title}  -  from {sn}  -  deadline {dl}")
        lines.append("  -> Open Slack to approve")
        lines.append("")
    if not pend:
        lines.append("(none)")
        lines.append("")

    lines.extend(
        [
            _SEP.strip(),
            f"UNSCHEDULABLE ({len(uns)} tasks)",
            _SEP.strip(),
        ]
    )
    for t in uns:
        title = str(t.get("title") or "(no title)")
        dl = t.get("deadline") or "Not specified"
        lines.append(f"- {title}  -  No free slot found before {dl}")
        lines.append("  -> Please schedule manually")
        lines.append("")
    if not uns:
        lines.append("(none)")
        lines.append("")

    lines.extend(
        [
            _SEP.strip(),
            f"AUTO-DISMISSED ({auto_email_total} emails)",
            _SEP.strip(),
            f"- {n} newsletters, {m} notifications, {k} promotional emails",
            "",
        ]
    )
    if dismissed_tasks:
        lines.append(f"Tasks you dismissed in the app: {len(dismissed_tasks)}")
        lines.append("")
    lines.extend(
        [
            _SEP.strip(),
            f"Generated by Task Scheduler Agent - {_now_iso()}",
        ]
    )
    return "\n".join(lines)


def _dismissed_email_counts() -> tuple[int, int, int]:
    """Optional env DIGEST_DISMISSED_COUNTS=n,m,k (newsletters, notifications, promotional)."""
    load_dotenv()
    raw = (os.getenv("DIGEST_DISMISSED_COUNTS") or "0,0,0").strip()
    parts = [p.strip() for p in raw.split(",")]
    while len(parts) < 3:
        parts.append("0")
    out: list[int] = []
    for p in parts[:3]:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return out[0], out[1], out[2]


def _clear_task_store() -> None:
    """Resets task_store.json to empty tasks with last_cleared timestamp."""
    file_store.save_task_store({"tasks": [], "last_cleared": _now_iso()})


def send_morning_digest() -> bool:
    """
    Loads task_store.json, builds digest email, sends via Gmail, then clears the store.

    Returns True if Gmail send succeeded. Always clears task_store afterward.
    """
    load_dotenv()
    to_addr = (os.getenv("YOUR_EMAIL") or "").strip()
    try:
        store = file_store.load_task_store()
        tasks = store.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
    except Exception as e:
        print(f"[ERROR][M6] load_task_store: {e}")
        tasks = []

    counts = _dismissed_email_counts()
    categories = _categorize_tasks(tasks)
    body = _build_digest_body(categories, counts)
    n_sched = len(categories["scheduled"])
    date_s = _digest_date_line()
    subject = f"Your day is planned - {n_sched} tasks scheduled - {date_s}"

    sent = False
    if not to_addr:
        print("[ERROR][M6] YOUR_EMAIL is not set; digest not sent")
    else:
        try:
            sent = gmail_client.send_email(to_addr, subject, body)
        except Exception as e:
            print(f"[ERROR][M6] send_email raised: {e}")
            sent = False

    try:
        _clear_task_store()
    except Exception as e:
        print(f"[ERROR][M6] _clear_task_store failed: {e}")

    if sent:
        print(f"[M6] Morning digest sent to {to_addr!r} ({n_sched} scheduled in body)")
    else:
        print("[M6] Morning digest not sent (store still cleared)")
    return sent
