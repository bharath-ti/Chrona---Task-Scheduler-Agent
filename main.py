"""
Task Scheduler Agent — orchestrator.

`run_pipeline()` runs M1 -> M2 -> M3 (M4+ not wired yet).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Project root (directory containing this file) on sys.path for imports
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def run_pipeline() -> dict[str, Any]:
    """
    Run M1 (fetch/filter), M2 (extract per email), M3 (dedupe + score + persist).

    Returns:
        {
            "email_count": int,
            "task_count": int,  # partial tasks from M2 before M3 merge
            "items": [...],     # per-email breakdown with M2 partial tasks
            "m3_stored_task_count": int,
            "m3_needs_approval_count": int,
            "m3_tasks": list[dict],  # full tasks returned by dedup_and_score
        }
    """
    from modules.m1_watcher import fetch_and_filter_emails
    from modules.m2_extractor import extract_tasks
    from modules.m3_scorer import dedup_and_score

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

    m3_needs_approval = sum(1 for t in scored_tasks if t.get("needs_approval"))

    summary: dict[str, Any] = {
        "email_count": len(emails),
        "task_count": len(all_partial_tasks),
        "items": items,
        "m3_stored_task_count": len(scored_tasks),
        "m3_needs_approval_count": m3_needs_approval,
        "m3_tasks": scored_tasks,
    }
    print(
        f"[pipeline] M1->M2->M3 complete: {summary['email_count']} email(s), "
        f"{summary['task_count']} extracted, "
        f"{summary['m3_stored_task_count']} task(s) in store after dedupe "
        f"({m3_needs_approval} need approval)"
    )
    return summary


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Task Scheduler Agent")
    p.add_argument(
        "--test",
        action="store_true",
        help="Run pipeline once (M1->M2->M3) and exit",
    )
    p.add_argument(
        "--m1-m2",
        action="store_true",
        dest="m1_m2",
        help="Alias for --test (full M1->M2->M3 run)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.test or args.m1_m2:
        result = run_pipeline()
        print(json.dumps(result, indent=2, default=str))
        return
    print("Usage: python main.py --test   (or --m1-m2)")
    print("Runs M1->M2->M3 pipeline once and prints JSON summary.")


if __name__ == "__main__":
    main()
