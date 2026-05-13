"""
Task Scheduler Agent — orchestrator.

`run_pipeline()` runs M1 -> M2 -> M3 -> M4 -> M5. `send_morning_digest()` is M6 (digest + clear store).
Use `--test` / `--digest` for one-shots or `--daemon` for the timed loop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import schedule
from dotenv import load_dotenv

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

    # Fresh load after M4 + timeouts so same-run DEMO_MODE approvals are visible to M5.
    try:
        final_store = file_store.load_task_store()
        final_tasks = final_store.get("tasks", [])
        if not isinstance(final_tasks, list):
            final_tasks = []
    except Exception as e:
        print(f"[ERROR][pipeline] load_task_store before M5: {e}")
        final_tasks = scored_tasks

    m5_booked = 0
    m5_skipped = 0
    m5_errors = 0
    for task in final_tasks:
        if not isinstance(task, dict):
            continue
        title = str(task.get("title") or "(no title)")
        st = str(task.get("status") or "")
        needs = bool(task.get("needs_approval"))
        timed_out = bool(task.get("timed_out"))

        if task.get("calendar_event_id"):
            print(f"[M5] Skipping {title}: status={st}, timed_out={timed_out}")
            m5_skipped += 1
            continue

        if timed_out:
            print(f"[M5] Skipping {title}: status={st}, timed_out={timed_out}")
            m5_skipped += 1
            continue

        # M5 runs only for: approved, auto_scheduled (retry without event), or
        # auto-extracted path (extracted + not needs_approval).
        # Skips: pending_approval, dismissed, scheduled, unschedulable, timed_out (above).
        eligible = (
            st == "approved"
            or st == "auto_scheduled"
            or (st == "extracted" and not needs)
        )
        if not eligible:
            print(f"[M5] Skipping {title}: status={st}, timed_out={timed_out}")
            m5_skipped += 1
            continue

        try:
            ev = find_and_book_slot(task)
            if ev:
                m5_booked += 1
            else:
                print(f"[M5] Skipping {title}: status={st}, timed_out={timed_out}")
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


def _normalize_digest_time(raw: str) -> str:
    """Return HH:MM for schedule (leading zeros)."""
    s = (raw or "08:00").strip()
    parts = s.split(":")
    if len(parts) != 2:
        return "08:00"
    try:
        h = max(0, min(23, int(parts[0])))
        m = max(0, min(59, int(parts[1])))
    except ValueError:
        return "08:00"
    return f"{h:02d}:{m:02d}"


def run_daemon_loop(
    poll_minutes: int | None = None,
    *,
    run_immediately: bool = True,
) -> None:
    """
    Run `run_pipeline()` on an interval (production-style loop).

    Does not set CHRONA_SKIP_LAST_RUN_UPDATE (M1 advances last_run as configured).
    Also schedules M6 morning digest at DIGEST_TIME (local clock for `schedule` library).

    Args:
        poll_minutes: Override interval; if None, uses CHRONA_POLL_MINUTES env or 5.
        run_immediately: If True, run one pipeline cycle before entering the wait loop.
    """
    from modules.m6_digest import send_morning_digest

    pm = poll_minutes if poll_minutes is not None else int(os.getenv("CHRONA_POLL_MINUTES", "5"))
    pm = max(1, pm)

    your_name = os.getenv("YOUR_NAME", "")
    your_email = os.getenv("YOUR_EMAIL", "")
    tz = os.getenv("TIMEZONE", "Asia/Kolkata")
    digest_raw = os.getenv("DIGEST_TIME", "08:00")
    digest = _normalize_digest_time(digest_raw)
    demo = os.getenv("DEMO_MODE", "false")

    def _job() -> None:
        try:
            run_pipeline()
        except Exception as e:
            print(f"[ERROR][daemon] run_pipeline: {e}")

    def _digest_job() -> None:
        try:
            send_morning_digest()
        except Exception as e:
            print(f"[ERROR][daemon] send_morning_digest: {e}")

    schedule.clear()

    print("=" * 50)
    print("Task Scheduler Agent (daemon)")
    print(f"Pipeline every {pm} minute(s) (M1->M2->M3->M4->M5)")
    print(f"Morning digest (M6) daily at: {digest} (from DIGEST_TIME={digest_raw!r})")
    print(f"User: {your_name} ({your_email})")
    print(f"Timezone: {tz}")
    print(f"DEMO_MODE: {demo}")
    print("Ctrl+C to stop")
    print("=" * 50)

    schedule.every(pm).minutes.do(_job)
    try:
        schedule.every().day.at(digest).do(_digest_job)
    except Exception as e:
        print(f"[ERROR][daemon] Could not schedule digest at {digest!r}: {e}")

    if run_immediately:
        _job()

    while True:
        schedule.run_pending()
        time.sleep(30)


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
    p.add_argument(
        "--daemon",
        action="store_true",
        help="Run pipeline on a timer (CHRONA_POLL_MINUTES, default 5). Updates last_run.",
    )
    p.add_argument(
        "--poll-minutes",
        type=int,
        default=None,
        metavar="N",
        help="With --daemon: poll interval in minutes (overrides CHRONA_POLL_MINUTES)",
    )
    p.add_argument(
        "--digest",
        action="store_true",
        help="Run M6 morning digest once (email + clear task_store), then exit",
    )
    return p.parse_args()


def main() -> None:
    load_dotenv()
    args = _parse_args()
    exclusive = (args.test or args.m1_m2, args.daemon, args.digest)
    if sum(1 for x in exclusive if x) > 1:
        print("[ERROR] Use only one of: --test / --m1-m2, --daemon, or --digest.")
        sys.exit(2)
    if args.daemon:
        try:
            run_daemon_loop(args.poll_minutes)
        except KeyboardInterrupt:
            print("\n[daemon] Stopped.")
        return
    if args.digest:
        from modules.m6_digest import send_morning_digest

        ok = send_morning_digest()
        print(json.dumps({"m6_digest_sent": ok}, indent=2))
        return
    if args.test or args.m1_m2:
        os.environ["CHRONA_SKIP_LAST_RUN_UPDATE"] = "true"
        try:
            result = run_pipeline()
            print(json.dumps(result, indent=2, default=str))
        finally:
            os.environ.pop("CHRONA_SKIP_LAST_RUN_UPDATE", None)
        return
    print("Usage:")
    print("  python main.py --test          # one-shot M1->M5 (skip last_run bump)")
    print("  python main.py --digest        # one-shot M6 digest + clear task_store")
    print("  python main.py --daemon        # M1->M5 poll + daily M6 at DIGEST_TIME")
    print("  python scripts/continuous_unittest.py   # re-run unit tests on an interval")


if __name__ == "__main__":
    main()
