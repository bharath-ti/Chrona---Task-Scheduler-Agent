"""
Task Scheduler Agent — orchestrator.

`run_pipeline()` runs M1 -> M2 -> M3 -> M4 -> M5 (M6 not wired yet).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Project root (directory containing this file) on sys.path for imports
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def run_pipeline() -> dict[str, Any]:
    """
    Run M1 (fetch/filter), M2 (extract per email), M3 (dedupe + score + persist),
    then M4 (Slack approval DMs + timeout sweep), then M5 (calendar booking).

    Returns:
        JSON-serializable summary including final tasks from task_store.json
        after M3/M4/M5 side effects.
    """
    from modules.m1_watcher import fetch_and_filter_emails
    from modules.m2_extractor import extract_tasks
    from modules.m3_scorer import dedup_and_score
    from modules.m4_approval import check_pending_timeouts, send_approval_request
    from modules.m5_scheduler import find_and_book_slot
    from utils import file_store

    try:
        emails = fetch_and_filter_emails()
    except Exception as e:
        print(f"[ERROR][pipeline] M1 failed: {e}")
        emails = []

    if not isinstance(emails, list):
        emails = []

    items: list[dict[str, Any]] = []
    all_partial_tasks: list[dict] = []

    for email in emails:
        try:
            tasks = extract_tasks(email)
        except Exception as e:
            print(f"[ERROR][pipeline] M2 failed for {email.get('subject', '')!r}: {e}")
            tasks = []

        if not isinstance(tasks, list):
            tasks = []

        all_partial_tasks.extend(tasks)
        items.append(
            {
                "message_id": str(email.get("message_id") or ""),
                "subject": str(email.get("subject") or ""),
                "is_transcript": bool(email.get("is_transcript")),
                "tasks": tasks,
            }
        )

    try:
        scored_tasks = dedup_and_score(all_partial_tasks)
    except Exception as e:
        print(f"[ERROR][pipeline] M3 failed: {e}")
        scored_tasks = []

    if not isinstance(scored_tasks, list):
        scored_tasks = []

    m4_sent = 0
    m4_failed = 0
    for task in scored_tasks:
        if not isinstance(task, dict):
            continue
        if not task.get("needs_approval"):
            continue
        if str(task.get("status", "")) != "extracted":
            continue
        if task.get("slack_message_ts"):
            continue
        try:
            if send_approval_request(task):
                m4_sent += 1
            else:
                m4_failed += 1
        except Exception as e:
            print(f"[ERROR][pipeline] M4 failed for task {task.get('id')!r}: {e}")
            m4_failed += 1

    try:
        check_pending_timeouts()
    except Exception as e:
        print(f"[ERROR][pipeline] check_pending_timeouts: {e}")

    try:
        final_store = file_store.load_task_store()
        final_tasks = final_store.get("tasks", [])
        if not isinstance(final_tasks, list):
            final_tasks = []
    except Exception as e:
        print(f"[ERROR][pipeline] load_task_store after M4: {e}")
        final_tasks = scored_tasks

    m5_booked = 0
    m5_skipped = 0
    m5_errors = 0
    for task in final_tasks:
        if not isinstance(task, dict):
            continue
        if task.get("calendar_event_id"):
            m5_skipped += 1
            continue
        st = str(task.get("status", ""))
        needs = bool(task.get("needs_approval"))
        eligible = st == "approved" or (st == "extracted" and not needs)
        if not eligible:
            m5_skipped += 1
            continue
        try:
            ev = find_and_book_slot(task)
            if ev:
                m5_booked += 1
            else:
                m5_skipped += 1
        except Exception as e:
            print(f"[ERROR][pipeline] M5 failed for task {task.get('id')!r}: {e}")
            m5_errors += 1

    try:
        final_store = file_store.load_task_store()
        final_tasks = final_store.get("tasks", [])
        if not isinstance(final_tasks, list):
            final_tasks = []
    except Exception as e:
        print(f"[ERROR][pipeline] load_task_store after M5: {e}")

    m3_needs_approval = sum(
        1 for t in final_tasks if isinstance(t, dict) and t.get("needs_approval")
    )

    summary: dict[str, Any] = {
        "email_count": len(emails),
        "task_count": len(all_partial_tasks),
        "items": items,
        "m3_stored_task_count": len(final_tasks),
        "m3_needs_approval_count": m3_needs_approval,
        "m3_tasks": final_tasks,
        "m4_approval_sent": m4_sent,
        "m4_approval_failed": m4_failed,
        "m5_booked": m5_booked,
        "m5_skipped": m5_skipped,
        "m5_errors": m5_errors,
    }
    print(
        f"[pipeline] M1->M2->M3->M4->M5 complete: {summary['email_count']} email(s), "
        f"{summary['task_count']} extracted, "
        f"{summary['m3_stored_task_count']} task(s) in store, "
        f"{m3_needs_approval} need approval, "
        f"M4 sent {m4_sent} / failed {m4_failed}, "
        f"M5 booked {m5_booked} (skipped {m5_skipped}, errors {m5_errors})"
    )
    return summary


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task Scheduler Agent")
    p.add_argument(
        "--test",
        action="store_true",
        help="Run pipeline once (M1->M2->M3->M4->M5) and exit",
    )
    p.add_argument(
        "--m1-m2",
        action="store_true",
        dest="m1_m2",
        help="Alias for --test (full M1->M2->M3->M4->M5 run)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.test or args.m1_m2:
        os.environ["CHRONA_SKIP_LAST_RUN_UPDATE"] = "true"
        try:
            result = run_pipeline()
            print(json.dumps(result, indent=2, default=str))
        finally:
            os.environ.pop("CHRONA_SKIP_LAST_RUN_UPDATE", None)
        return
    print("Usage: python main.py --test   (or --m1-m2)")
    print("Runs M1->M2->M3->M4->M5 pipeline once and prints JSON summary.")


if __name__ == "__main__":
    main()
