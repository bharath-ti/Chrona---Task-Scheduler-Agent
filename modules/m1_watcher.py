"""Gmail polling and filtering — entry point for the task pipeline (M1)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from pathlib import Path

import pytz
from dotenv import load_dotenv

from utils import file_store
from utils import gmail_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PEOPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "people_config.json"

BLOCKLIST_SENDERS = [
    "noreply@",
    "no-reply@",
    "notifications@",
    "alerts@",
    "donotreply@",
    "mailer@",
    "newsletter@",
    "digest@",
    "linkedin.com",
    "medium.com",
    "twitter.com",
    "github.com",
]

BLOCKLIST_SUBJECTS = [
    "newsletter",
    "unsubscribe",
    "job alert",
    "linkedin digest",
    "weekly digest",
    "your receipt",
    "order confirmation",
    "verification code",
    "otp",
    "invoice from",
]

TRANSCRIPT_SIGNALS = [
    "transcript",
    "meeting notes",
    "meeting summary",
    "read.ai",
    "otter.ai",
    "zoom recording",
    "teams meeting notes",
]


class _HTMLToText(HTMLParser):
    """Collect visible text from HTML for plain-text downstream use."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _strip_html_to_text(html: str) -> str:
    """Strips tags to approximate plain text; returns non-HTML as-is."""
    if not html or "<" not in html:
        return html.strip()
    try:
        parser = _HTMLToText()
        parser.feed(html)
        parser.close()
        text = parser.get_text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_people_config() -> dict:
    """Loads config/people_config.json. Returns {"people": []} on error."""
    try:
        with open(PEOPLE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"people": []}
        people = data.get("people", [])
        if not isinstance(people, list):
            return {"people": []}
        return {"people": people}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR][M1] Failed to load people config: {e}")
        return {"people": []}


def _get_sender_context(sender_email: str, people: list) -> tuple[str, str, int]:
    """
    Looks up sender in people list.
    Returns: (role, name, weight) — defaults to ("unknown", sender_email, 3)
    """
    target = (sender_email or "").strip().lower()
    for entry in people:
        if not isinstance(entry, dict):
            continue
        email = str(entry.get("email", "")).strip().lower()
        if email and email == target:
            role = str(entry.get("role", "unknown")).strip() or "unknown"
            name = str(entry.get("name", "")).strip() or sender_email
            weight = entry.get("priority_weight", 3)
            try:
                w = int(weight)
            except (TypeError, ValueError):
                w = 3
            return role, name, w
    return "unknown", sender_email or "", 3


def _emails_in_header(header_value: str) -> set[str]:
    """Lowercased recipient emails from a To/Cc header string."""
    if not header_value:
        return set()
    return {
        addr.strip().lower()
        for _, addr in getaddresses([header_value])
        if addr and addr.strip()
    }


def _is_noise(
    subject: str,
    sender_email: str,
    to_field: str,
    your_email: str,
    cc_field: str = "",
) -> bool:
    """
    Returns True if email should be skipped.
    Checks: blocklist senders, blocklist subjects, CC-only (not in TO field).

    When cc_field is empty, the CC-only rule is skipped (cannot be evaluated).
    """
    subj = (subject or "").lower()
    snd = (sender_email or "").lower()
    you = (your_email or "").strip().lower()
    for pattern in BLOCKLIST_SENDERS:
        if pattern.lower() in snd:
            return True
    for phrase in BLOCKLIST_SUBJECTS:
        if phrase.lower() in subj:
            return True
    if you and cc_field.strip():
        in_to = you in _emails_in_header(to_field)
        in_cc = you in _emails_in_header(cc_field)
        if not in_to and in_cc:
            return True
    return False


def _is_transcript(subject: str, sender_email: str, body: str) -> bool:
    """Returns True if email is a meeting transcript based on TRANSCRIPT_SIGNALS."""
    hay = f"{subject or ''}\n{sender_email or ''}\n{body or ''}".lower()
    return any(sig.lower() in hay for sig in TRANSCRIPT_SIGNALS)


def _update_last_run() -> None:
    """Writes current timestamp to data/last_run.json (timezone-aware)."""
    try:
        load_dotenv()
        tz_name = os.getenv("TIMEZONE", "Asia/Kolkata")
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
    except Exception:
        now = datetime.now(pytz.UTC)
    file_store.save_last_run(now.isoformat())


def _parse_sender(from_header: str) -> tuple[str, str]:
    """Returns (display_name, email_address) from a From header."""
    name, addr = parseaddr(from_header or "")
    addr_clean = (addr or "").strip().lower()
    display = (name or "").strip()
    if not display:
        display = addr_clean or (from_header or "").strip()
    return display, addr_clean or (from_header or "").strip().lower()


def fetch_and_filter_emails() -> list[dict]:
    """
    Main entry point for M1. Polls Gmail for new emails since last run,
    filters noise, and returns qualifying email dicts ready for M2.

    Returns:
        List of email dicts, each containing:
        {
            "message_id": str,
            "subject": str,
            "body": str,           # Plain text body, HTML stripped
            "sender_email": str,   # Extracted from From header
            "sender_name": str,
            "sender_role": str,    # From people_config, default "unknown"
            "sender_weight": int,  # From people_config, default 3
            "timestamp": str,      # ISO 8601
            "is_transcript": bool  # True if meeting transcript detected
        }
    Returns [] on any error — never raises.
    """
    try:
        load_dotenv()
        your_email = (os.getenv("YOUR_EMAIL") or "").strip()
        people_cfg = _load_people_config()
        people = people_cfg.get("people", [])
        since = file_store.load_last_run()
        raw = gmail_client.get_unread_since(since)
        filtered: list[dict] = []
        for msg in raw:
            subject = str(msg.get("subject") or "")
            body_raw = str(msg.get("body") or "")
            body = _strip_html_to_text(body_raw)
            to_field = str(msg.get("to") or "")
            cc_field = str(msg.get("cc") or "")
            from_header = str(msg.get("from") or "")
            sender_name, sender_email = _parse_sender(from_header)
            if _is_noise(subject, sender_email, to_field, your_email, cc_field):
                continue
            role, resolved_name, weight = _get_sender_context(sender_email, people)
            display_name = resolved_name if resolved_name else sender_name
            ts = str(msg.get("date") or "")
            is_tr = _is_transcript(subject, sender_email, body)
            filtered.append(
                {
                    "message_id": str(msg.get("id") or ""),
                    "subject": subject,
                    "body": body,
                    "sender_email": sender_email,
                    "sender_name": display_name,
                    "sender_role": role,
                    "sender_weight": weight,
                    "timestamp": ts,
                    "is_transcript": is_tr,
                }
            )
        print(f"[M1] Fetched {len(raw)} emails, {len(filtered)} passed filters")
        _update_last_run()
        return filtered
    except Exception as e:
        print(f"[ERROR][M1] fetch_and_filter_emails failed: {e}")
        return []
