"""
Slack interactive app — Socket Mode.

Run from project root:
  python slack_socket.py

Requires SLACK_BOT_TOKEN, SLACK_APP_TOKEN (xapp-), SLACK_SIGNING_SECRET optional for Socket Mode.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _main() -> None:
    load_dotenv()
    bot_token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
    app_token = (os.getenv("SLACK_APP_TOKEN") or "").strip()
    signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip() or None

    if not bot_token or not app_token:
        print(
            "[ERROR] SLACK_BOT_TOKEN and SLACK_APP_TOKEN (Socket Mode) are required."
        )
        sys.exit(1)

    app = App(token=bot_token, signing_secret=signing_secret)

    @app.action("approve_task")
    def on_approve(ack, body):  # type: ignore[no-untyped-def]
        ack()
        try:
            task_id = body["actions"][0]["value"]
            from modules.m4_approval import handle_approve

            handle_approve(task_id)
        except Exception as e:
            print(f"[ERROR][slack_socket] approve_task: {e}")

    @app.action("dismiss_task")
    def on_dismiss(ack, body):  # type: ignore[no-untyped-def]
        ack()
        try:
            task_id = body["actions"][0]["value"]
            from modules.m4_approval import handle_dismiss

            handle_dismiss(task_id)
        except Exception as e:
            print(f"[ERROR][slack_socket] dismiss_task: {e}")

    @app.action("edit_task_time")
    def on_edit_time_stub(ack, body):  # type: ignore[no-untyped-def]
        ack()
        try:
            task_id = body.get("actions", [{}])[0].get("value", "")
        except Exception:
            task_id = ""
        print(f"[M4] edit_task_time (stub): not implemented in v1 (task_id={task_id!r})")

    print("=" * 50)
    print("Slack Socket Mode handler starting...")
    print("Listening for block actions: approve_task, dismiss_task, edit_task_time (stub)")
    print("=" * 50)

    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    _main()
