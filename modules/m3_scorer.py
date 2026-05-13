"""M3 — deduplicate tasks, compute priority_score, set needs_approval, persist."""

from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime
from typing import Any

import pytz
from dotenv import load_dotenv

from utils import file_store

URGENCY_SCORES = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 1,
}

_STOPWORDS = frozenset(
    {"the", "a", "an", "is", "to", "for", "of", "and", "in", "on", "at"}
)

_WORKFLOW_STATUSES = frozenset(
    {
        "pending_approval",
        "approved",
        "scheduled",
        "unschedulable",
        "auto_scheduled",
        "dismissed",
    }
)


def _timezone() -> Any:
    load_dotenv()
    return pytz.timezone(os.getenv("TIMEZONE", "Asia/Kolkata"))


def _now_iso() -> str:
    return datetime.now(_timezone()).isoformat()


def _parse_iso(dt_str: str) -> datetime:
    s = dt_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = _timezone().localize(dt)
    else:
        dt = dt.astimezone(_timezone())
    return dt


def deadline_proximity_score(deadline_iso: str | None) -> int:
    """
    null/no deadline → 1
    > 7 days away   → 2
    3-7 days away   → 4
    1-3 days away   → 7
    12-24 hours     → 8
    < 12 hours      → 10
    """
    if deadline_iso is None or str(deadline_iso).strip() in ("", "null"):
        return 1
    try:
        deadline = _parse_iso(str(deadline_iso))
    except (ValueError, TypeError):
        return 1
    now = datetime.now(_timezone())
    delta = deadline - now
    hours = delta.total_seconds() / 3600.0
    if hours <= 0:
        return 10
    if hours < 12:
        return 10
    if hours < 24:
        return 8
    days = hours / 24.0
    if days <= 3:
        return 7
    if days <= 7:
        return 4
    return 2


def duration_score(estimated_minutes: int) -> int:
    """
    > 120 min → 10
    60-120    → 7
    30-60     → 5
    < 30      → 3
    """
    try:
        m = int(estimated_minutes)
    except (TypeError, ValueError):
        m = 30
    if m > 120:
        return 10
    if m >= 60:
        return 7
    if m >= 30:
        return 5
    return 3


def _word_overlap(title_a: str, title_b: str) -> float:
    """
    Returns overlap ratio between 0.0 and 1.0.
    Uses lowercase word sets, ignores stopwords (the, a, an, is, to, for, of).
    Threshold: > 0.70 = duplicate.
    """
    words_a = set(title_a.lower().split()) - _STOPWORDS
    words_b = set(title_b.lower().split()) - _STOPWORDS
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def _hours_until_deadline(deadline_iso: str | None) -> float | None:
    if deadline_iso is None or str(deadline_iso).strip() in ("", "null"):
        return None
    try:
        deadline = _parse_iso(str(deadline_iso))
        now = datetime.now(_timezone())
        return (deadline - now).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def _score_task(task: dict) -> float:
    """Calculates and returns the priority_score for a single task."""
    try:
        w = float(task.get("sender_weight", 3))
    except (TypeError, ValueError):
        w = 3.0
    w = max(0.0, min(10.0, w))

    urg = str(task.get("urgency", "medium")).strip().lower()
    urgency_score = float(URGENCY_SCORES.get(urg, 4))

    dp = float(deadline_proximity_score(task.get("deadline")))
    try:
        em = int(task.get("estimated_minutes", 30))
    except (TypeError, ValueError):
        em = 30
    dur = float(duration_score(em))

    raw = w * 0.35 + urgency_score * 0.30 + dp * 0.25 + dur * 0.10
    return min(10.0, round(raw, 2))


def _needs_approval(task: dict) -> bool:
    score = float(task.get("priority_score", 0))
    role = str(task.get("sender_role", "")).strip()
    if score >= 7.0:
        return True
    if role in ("VP", "client"):
        return True
    h = _hours_until_deadline(task.get("deadline"))
    if h is not None and h < 12:
        return True
    return False


def _normalize_sources(task: dict) -> list[str]:
    s = task.get("sources")
    if isinstance(s, list) and s:
        out = [str(x) for x in s if x in ("email", "transcript")]
        if out:
            return out
    one = task.get("source")
    if one in ("email", "transcript"):
        return [str(one)]
    return ["email"]


def _union_sources(into: dict, fr: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in _normalize_sources(into) + _normalize_sources(fr):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out if out else ["email"]


def _earliest_deadline(a: str | None, b: str | None) -> str | None:
    if a is None or str(a).strip() in ("", "null"):
        return None if (b is None or str(b).strip() in ("", "null")) else str(b)
    if b is None or str(b).strip() in ("", "null"):
        return str(a)
    try:
        da = _parse_iso(str(a))
        db = _parse_iso(str(b))
        return da.isoformat() if da <= db else db.isoformat()
    except (ValueError, TypeError):
        return str(a)


def _find_duplicate_index(combined: list[dict], title: str) -> int | None:
    for i, t in enumerate(combined):
        if _word_overlap(str(t.get("title", "")), title) > 0.70:
            return i
    return None


def _merge_into(into: dict, fr: dict) -> None:
    """Merge duplicate `fr` into canonical `into` (first occurrence)."""
    into["deadline"] = _earliest_deadline(into.get("deadline"), fr.get("deadline"))
    into["sources"] = _union_sources(into, fr)
    into["source"] = into["sources"][0] if into["sources"] else "email"

    try:
        w_in = int(into.get("sender_weight", 3))
    except (TypeError, ValueError):
        w_in = 3
    try:
        w_fr = int(fr.get("sender_weight", 3))
    except (TypeError, ValueError):
        w_fr = 3
    if w_fr > w_in:
        into["sender_weight"] = w_fr
        into["sender"] = fr.get("sender", into.get("sender"))
        into["sender_name"] = fr.get("sender_name", into.get("sender_name"))
        into["sender_role"] = fr.get("sender_role", into.get("sender_role"))

    into["seen_count"] = int(into.get("seen_count", 1)) + 1
    into["updated_at"] = _now_iso()

    st = str(into.get("status", "extracted"))
    if st not in _WORKFLOW_STATUSES:
        into["status"] = "extracted"


def _new_full_task_from_m2(raw: dict) -> dict:
    """Build a full task row from M2 partial dict."""
    now = _now_iso()
    src = raw.get("source", "email")
    if src not in ("email", "transcript"):
        src = "email"
    sources = [src]
    try:
        sw = int(raw.get("sender_weight", 3))
    except (TypeError, ValueError):
        sw = 3
    urg = str(raw.get("urgency", "medium")).strip().lower()
    if urg not in URGENCY_SCORES:
        urg = "medium"
    dl = raw.get("deadline")
    if dl is not None and str(dl).strip() in ("", "null"):
        dl = None
    try:
        em = int(raw.get("estimated_minutes", 30))
    except (TypeError, ValueError):
        em = 30
    if em < 1:
        em = 1

    return {
        "id": str(uuid.uuid4()),
        "title": str(raw.get("title", "")).strip(),
        "description": str(raw.get("description", "")).strip(),
        "deadline": dl,
        "estimated_minutes": em,
        "source": src,
        "sources": sources,
        "sender": str(raw.get("sender", "")),
        "sender_name": str(raw.get("sender_name", "")),
        "sender_role": str(raw.get("sender_role", "unknown")),
        "sender_weight": sw,
        "urgency": urg,
        "raw_snippet": str(raw.get("raw_snippet", "")),
        "priority_score": 0.0,
        "needs_approval": False,
        "status": "extracted",
        "calendar_event_id": None,
        "slack_message_ts": None,
        "seen_count": 1,
        "created_at": now,
        "updated_at": now,
    }


def _assign_ids_and_defaults(tasks: list[dict]) -> list[dict]:
    """Adds id (uuid4), status='extracted', created_at, updated_at, seen_count=1 where missing."""
    now = _now_iso()
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if not t.get("id"):
            t["id"] = str(uuid.uuid4())
        if not t.get("status"):
            t["status"] = "extracted"
        if "seen_count" not in t or t["seen_count"] is None:
            t["seen_count"] = 1
        if not t.get("created_at"):
            t["created_at"] = now
        if not t.get("updated_at"):
            t["updated_at"] = now
        if "calendar_event_id" not in t:
            t["calendar_event_id"] = None
        if "slack_message_ts" not in t:
            t["slack_message_ts"] = None
        if not t.get("sources"):
            t["sources"] = _normalize_sources(t)
        if t.get("source") not in ("email", "transcript"):
            t["source"] = t["sources"][0] if t.get("sources") else "email"
    return tasks


def dedup_and_score(new_tasks: list[dict]) -> list[dict]:
    """
    Main entry point for M3.

    Args:
        new_tasks: List of partial task dicts from M2 (no id/status/score yet)

    Returns:
        Full list of all tasks (existing + new, deduplicated), sorted by
        priority_score descending. Each task has id, priority_score,
        needs_approval, status="extracted" added.
        Also saves updated list to task_store.json.
    """
    try:
        store = file_store.load_task_store()
        existing = store.get("tasks", [])
        if not isinstance(existing, list):
            existing = []
        combined: list[dict] = [copy.deepcopy(t) for t in existing if isinstance(t, dict)]

        incoming = new_tasks if isinstance(new_tasks, list) else []
        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            if not title:
                continue
            dup_idx = _find_duplicate_index(combined, title)
            if dup_idx is not None:
                _merge_into(combined[dup_idx], raw)
            else:
                combined.append(_new_full_task_from_m2(raw))

        _assign_ids_and_defaults(combined)

        for t in combined:
            t["priority_score"] = _score_task(t)
            t["needs_approval"] = _needs_approval(t)

        combined.sort(key=lambda x: -float(x.get("priority_score", 0)))

        out_store: dict[str, Any] = {"tasks": combined}
        if "last_cleared" in store:
            out_store["last_cleared"] = store["last_cleared"]
        file_store.save_task_store(out_store)

        need_appr = sum(1 for t in combined if t.get("needs_approval"))
        print(
            f"[M3] Scored {len(combined)} task(s), {need_appr} need approval "
            f"({len(incoming)} new raw this batch)"
        )
        return combined
    except Exception as e:
        print(f"[ERROR][M3] dedup_and_score failed: {e}")
        return []
