"""Slack Web API helpers for DMs and message updates."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def send_dm(
    user_id: str,
    text: str | None = None,
    blocks: list | None = None,
) -> dict[str, str] | None:
    """
    Sends a DM to user_id.

    Returns:
        {"ts": str, "channel": str} on success (channel is the DM id for chat.update).
        None on failure.
    """
    try:
        load_dotenv()
        token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
        if not token:
            print("[ERROR][slack_client] SLACK_BOT_TOKEN is not set")
            return None
        uid = (user_id or "").strip()
        if not uid:
            print("[ERROR][slack_client] send_dm: empty user_id")
            return None

        client = WebClient(token=token)
        open_resp = client.conversations_open(users=uid)
        if not open_resp.get("ok"):
            print(f"[ERROR][slack_client] conversations_open failed: {open_resp}")
            return None
        channel = open_resp["channel"]["id"]
        body: dict[str, Any] = {"channel": channel}
        if blocks is not None:
            body["blocks"] = blocks
            body["text"] = (text or "Task approval request").strip() or "Task approval request"
        else:
            body["text"] = text or ""

        post = client.chat_postMessage(**body)
        if not post.get("ok"):
            print(f"[ERROR][slack_client] chat_postMessage failed: {post}")
            return None
        ts = post.get("ts")
        if not ts:
            print("[ERROR][slack_client] chat_postMessage missing ts")
            return None
        return {"ts": str(ts), "channel": str(channel)}
    except SlackApiError as e:
        print(f"[ERROR][slack_client] Slack API error: {e}")
        return None
    except Exception as e:
        print(f"[ERROR][slack_client] send_dm failed: {e}")
        return None


def update_message(
    channel: str, ts: str, text: str, blocks: list | None = None
) -> None:
    """Updates an existing Slack message (used to mark approved/dismissed)."""
    try:
        load_dotenv()
        token = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
        if not token:
            print("[ERROR][slack_client] SLACK_BOT_TOKEN is not set")
            return
        client = WebClient(token=token)
        kwargs: dict[str, Any] = {
            "channel": channel,
            "ts": ts,
            "text": text,
        }
        if blocks is not None:
            kwargs["blocks"] = blocks
        client.chat_update(**kwargs)
    except SlackApiError as e:
        print(f"[ERROR][slack_client] Slack API error (update_message): {e}")
    except Exception as e:
        print(f"[ERROR][slack_client] update_message failed: {e}")
