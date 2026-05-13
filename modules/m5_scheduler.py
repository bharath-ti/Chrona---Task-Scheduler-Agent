"""M5 — Google Calendar scheduling (find_and_book_slot, slot finder)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, time as dt_time
from typing import Any

import pytz
from dotenv import load_dotenv

from utils import file_store
from utils import slack_client
from utils.calendar_client import create_event, event_bounds_utc, get_events

URGENCY_COLORS: dict[str, str] = {
    "critical": "11",
    "high": "5",
    "medium": "9",
    "low": "8",
}


def _timezone() -> Any:
    load_dotenv()
    return pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))


def _now_iso() -> str:
    return datetime.now(_timezone()).isoformat()


def _parse_iso(dt_str: str | None) -> datetime | None:
    if dt_str is None or str(dt_str).strip() in ("", "null"):
        return None
    try:
        s = str(dt_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = _timezone().localize(dt)
        else:
            dt = dt.astimezone(_timezone())
        return dt
    except (ValueError, TypeError):
        return None


def _working_hours() -> tuple[int, int]:
    load_dotenv()
    try:
        start_h = int(os.getenv("WORKING_HOURS_START", "9"))
    except ValueError:
        start_h = 9
    try:
        end_h = int(os.getenv("WORKING_HOURS_END", "20"))
    except ValueError:
        end_h = 20
    return start_h, end_h


def _estimated_minutes(task: dict[str, Any]) -> int:
    try:
        m = int(task.get("estimated_minutes", 0))
    except (TypeError, ValueError):
        m = 0
    return max(m, 15)


def _window_end(now: datetime, deadline: datetime | None) -> datetime:
    if deadline is not None and deadline > now:
        return deadline
    return now + timedelta(days=7)


def _merge_busy(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def _get_busy_windows(start_dt: datetime, end_dt: datetime) -> list[tuple[datetime, datetime]]:
    """
    Fetches calendar events and returns merged busy (start, end) in local timezone,
    clipped to [start_dt, end_dt] (same tz as start_dt).
    """
    tz = _timezone()
    if start_dt.tzinfo is None:
        start_dt = tz.localize(start_dt)
    else:
        start_dt = start_dt.astimezone(tz)
    if end_dt.tzinfo is None:
        end_dt = tz.localize(end_dt)
    else:
        end_dt = end_dt.astimezone(tz)
    if end_dt <= start_dt:
        return []

    tz_name = os.getenv("TIMEZONE", "Asia/Kolkata")
    raw = get_events(start_dt.astimezone(pytz.UTC), end_dt.astimezone(pytz.UTC))
    bounds: list[tuple[datetime, datetime]] = []
    for ev in raw:
        b = event_bounds_utc(ev, tz_name)
        if b is None:
            continue
        s_utc, e_utc = b
        s = s_utc.astimezone(tz)
        e = e_utc.astimezone(tz)
        if e <= start_dt or s >= end_dt:
            continue
        s = max(s, start_dt)
        e = min(e, end_dt)
        if e > s:
            bounds.append((s, e))
    return _merge_busy(bounds)


def _find_free_slot(
    busy_windows: list[tuple[datetime, datetime]],
    now: datetime,
    window_end: datetime,
    deadline: datetime | None,
    required_minutes: int,
    estimated_minutes: int,
) -> tuple[datetime, datetime] | None:
    """
    Core slot search. Returns (slot_start, slot_end) in local TZ or None.
    required_minutes is the minimum gap size (estimated + buffer).
    """
    tz = _timezone()
    if now.tzinfo is None:
        now = tz.localize(now)
    else:
        now = now.astimezone(tz)
    if window_end.tzinfo is None:
        window_end = tz.localize(window_end)
    else:
        window_end = window_end.astimezone(tz)
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = tz.localize(deadline)
        else:
            deadline = deadline.astimezone(tz)

    wh_start_h, wh_end_h = _working_hours()
    busy = _merge_busy([(s.astimezone(tz), e.astimezone(tz)) for s, e in busy_windows])

    day = now.date()
    last_day = window_end.date()
    while day <= last_day:
        work_start = tz.localize(datetime.combine(day, dt_time(wh_start_h, 0)))
        work_end = tz.localize(datetime.combine(day, dt_time(wh_end_h, 0)))
        day_start = max(now, work_start)
        day_end = work_end
        if day_start >= day_end:
            day += timedelta(days=1)
            continue

        day_busy = [
            (max(s, day_start), min(e, day_end))
            for s, e in busy
            if e > day_start and s < day_end
        ]
        day_busy = _merge_busy(day_busy)

        cursor = day_start
        for b_start, b_end in day_busy:
            gap_start, gap_end = cursor, b_start
            gap_minutes = (gap_end - gap_start).total_seconds() / 60.0
            if gap_minutes >= required_minutes:
                slot_start = gap_start
                slot_end = slot_start + timedelta(minutes=estimated_minutes)
                if slot_end <= gap_end and slot_end <= day_end:
                    if deadline is None or slot_end <= deadline:
                        return slot_start, slot_end
            cursor = max(cursor, b_end)

        gap_start, gap_end = cursor, day_end
        gap_minutes = (gap_end - gap_start).total_seconds() / 60.0
        if gap_minutes >= required_minutes:
            slot_start = gap_start
            slot_end = slot_start + timedelta(minutes=estimated_minutes)
            if slot_end <= gap_end:
                if deadline is None or slot_end <= deadline:
                    return slot_start, slot_end

        day += timedelta(days=1)

    return None


def _compute_slot(task: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Returns first viable (slot_start, slot_end) in local timezone, or None."""
    tz = _timezone()
    now = datetime.now(tz)
    deadline = _parse_iso(task.get("deadline")) if task.get("deadline") not in (None, "", "null") else None
    window_end = _window_end(now, deadline)
    est = _estimated_minutes(task)
    required = est + 30
    busy = _get_busy_windows(now, window_end)
    return _find_free_slot(busy, now, window_end, deadline, required, est)


def _urgency_to_color(urgency: str) -> str:
    u = str(urgency or "medium").lower()
    return URGENCY_COLORS.get(u, URGENCY_COLORS["medium"])


def _format_slot_label(slot_start: datetime, slot_end: datetime) -> str:
    """Human-readable slot, e.g. '9:00 AM – 11:00 AM tomorrow' (local TZ)."""
    tz = _timezone()
    a = slot_start.astimezone(tz)
    b = slot_end.astimezone(tz)
    today = datetime.now(tz).date()
    tomorrow = today + timedelta(days=1)

    def fmt_t(d: datetime) -> str:
        t = d.timetz()
        h12 = t.hour % 12
        if h12 == 0:
            h12 = 12
        ampm = "AM" if t.hour < 12 else "PM"
        return f"{h12}:{t.minute:02d} {ampm}"

    day_hint = ""
    if a.date() == tomorrow:
        day_hint = " tomorrow"
    elif a.date() != today:
        day_hint = f" on {a.strftime('%a %d %b')}"

    return f"{fmt_t(a)} – {fmt_t(b)}{day_hint}"


def find_next_free_slot(task: dict[str, Any]) -> str | None:
    """
    Returns a human-readable string of the next free slot for this task.
    Used by M4 to show proposed slot in Slack. None if no slot found.
    """
    try:
        slot = _compute_slot(task)
        if slot is None:
            return None
        s, e = slot
        return _format_slot_label(s, e)
    except Exception as e:
        print(f"[ERROR][M5] find_next_free_slot failed: {e}")
        return None


def _m5_booked_status(task: dict[str, Any]) -> str:
    if str(task.get("status", "")) == "approved":
        return "scheduled"
    return "auto_scheduled"


def _build_event_body(task: dict[str, Any], slot_start: datetime, slot_end: datetime) -> dict[str, Any]:
    load_dotenv()
    tz_name = os.getenv("TIMEZONE", "Asia/Kolkata")
    try:
        score = float(task.get("priority_score", 0))
    except (TypeError, ValueError):
        score = 0.0
    urgency = str(task.get("urgency") or "medium")
    est = _estimated_minutes(task)
    desc = (
        f"From: {task.get('sender_name', '')} ({task.get('sender_role', '')}) "
        f"via {task.get('source', 'email')}\n"
        f"Deadline: {task.get('deadline') or 'Not specified'}\n"
        f"Priority: {urgency.capitalize()} · Score {score:.1f}\n"
        f"Estimated: {est} minutes\n\n"
        f"Source snippet:\n\"{task.get('raw_snippet', '')}\"\n\n"
        f"Scheduled by: Task Scheduler Agent"
    )
    return {
        "summary": str(task.get("title", "Task")),
        "description": desc,
        "start": {"dateTime": slot_start.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": slot_end.isoformat(), "timeZone": tz_name},
        "colorId": _urgency_to_color(urgency),
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 15}],
        },
    }


def _send_unschedulable_dm(task: dict[str, Any]) -> None:
    load_dotenv()
    uid = (os.getenv("SLACK_USER_ID") or "").strip()
    if not uid:
        return
    title = str(task.get("title", ""))
    dl = task.get("deadline") or "Not specified"
    text = (
        "[WARNING] No free slot found for: "
        f"{title}\nDeadline: {dl}\n"
        "Your calendar is fully booked. Please reschedule manually."
    )
    try:
        slack_client.send_dm(uid, text=text)
    except Exception as e:
        print(f"[ERROR][M5] unschedulable DM failed: {e}")


def find_and_book_slot(task: dict[str, Any]) -> dict[str, Any] | None:
    """
    Finds a free calendar slot and creates a Google Calendar event.

    Calendar creation does not require the task row to exist in task_store;
    persisting updates is best-effort only. Slack DM if unschedulable.
    """
    tid = str(task.get("id") or "").strip()
    if not tid:
        print("[ERROR][M5] find_and_book_slot: task has no id")
        return None
    if task.get("calendar_event_id"):
        print(f"[M5] skip: task {tid!r} already has calendar_event_id")
        return None

    st = str(task.get("status") or "").strip()
    if not st:
        st = "extracted"
    needs = bool(task.get("needs_approval"))
    eligible = st == "approved" or (st == "extracted" and not needs)
    if not eligible:
        print(
            f"[M5] skip: not eligible for scheduling "
            f"(status={st!r}, needs_approval={needs})"
        )
        return None

    try:
        slot = _compute_slot(task)
    except Exception as e:
        print(f"[ERROR][M5] _compute_slot failed: {e}")
        return None

    if slot is None:
        print(f"[M5] no free slot for task id={tid!r} title={task.get('title')!r}")
        try:
            file_store.update_task(
                tid,
                {
                    "status": "unschedulable",
                    "updated_at": _now_iso(),
                },
            )
        except Exception as e:
            print(f"[ERROR][M5] update_task (unschedulable) failed: {e}")
        _send_unschedulable_dm(task)
        return None

    slot_start, slot_end = slot
    print(
        f"[M5] slot found: {slot_start.isoformat()} -> {slot_end.isoformat()} "
        f"(tz={os.getenv('TIMEZONE', 'Asia/Kolkata')})"
    )

    body = _build_event_body(task, slot_start, slot_end)
    print(
        "[M5] create_event body: "
        f"summary={body.get('summary')!r} start={body.get('start')!r} end={body.get('end')!r}"
    )

    created: dict[str, Any] | None
    try:
        created = create_event(body)
    except Exception as e:
        print(f"[ERROR][M5] create_event raised: {e}")
        created = None

    print(
        f"[M5] create_event returned: "
        f"{type(created).__name__} "
        f"id={(created.get('id') if isinstance(created, dict) else None)!r}"
    )

    if not created:
        title = str(task.get("title", "") or "")
        print(f"[ERROR][M5] create_event returned None for {title!r}")
        print(
            "[ERROR][M5] create_event None: check Calendar API logs above, "
            "credentials/token scopes, and HTTP errors from calendar_client"
        )
        return None

    title = str(task.get("title", "") or "")
    print(f"[M5] Scheduled: {title}")
    try:
        ev_id = str(created.get("id") or "")
        new_status = _m5_booked_status(task)
        file_store.update_task(
            tid,
            {
                "status": new_status,
                "calendar_event_id": ev_id or None,
                "scheduled_start": slot_start.isoformat(),
                "scheduled_end": slot_end.isoformat(),
                "updated_at": _now_iso(),
            },
        )
    except Exception as e:
        print(
            f"[ERROR][M5] update_task after schedule failed (event was still created): {e}"
        )

    return created
