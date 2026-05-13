"""Gmail API wrapper: read unread messages and (later) send mail."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

import pytz
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.google_scopes import GOOGLE_OAUTH_SCOPES

SCOPES: list[str] = GOOGLE_OAUTH_SCOPES


def _credentials_path() -> str:
    load_dotenv()
    return os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")


def _token_path() -> str:
    load_dotenv()
    return os.getenv("GOOGLE_TOKEN_PATH", "token.json")


def _get_gmail_service():
    """Builds an authorized Gmail API service."""
    creds: Credentials | None = None
    token_path = _token_path()
    if os.path.isfile(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"[ERROR][gmail_client] Failed to load token: {e}")
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[ERROR][gmail_client] Token refresh failed: {e}")
                creds = None
        if not creds or not creds.valid:
            client_secrets = _credentials_path()
            if not os.path.isfile(client_secrets):
                print(
                    f"[ERROR][gmail_client] Missing OAuth client file: {client_secrets}"
                )
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secrets, SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"[ERROR][gmail_client] OAuth flow failed: {e}")
                return None
        try:
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        except OSError as e:
            print(f"[ERROR][gmail_client] Could not save token: {e}")
    try:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[ERROR][gmail_client] build() failed: {e}")
        return None


def _header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _b64url_decode(data: str) -> str:
    if not data:
        return ""
    pad = "=" * (-len(data) % 4)
    try:
        raw = base64.urlsafe_b64decode((data + pad).encode("ascii"))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _collect_bodies(part: dict[str, Any]) -> tuple[str, str]:
    """Returns (plain_text, html) from a MIME part tree."""
    mime = (part.get("mimeType") or "").lower()
    body = part.get("body") or {}
    data = body.get("data")
    text_plain = ""
    text_html = ""
    if mime == "text/plain" and data:
        text_plain = _b64url_decode(data)
    elif mime == "text/html" and data:
        text_html = _b64url_decode(data)
    for sub in part.get("parts") or []:
        p, h = _collect_bodies(sub)
        if p:
            text_plain = text_plain or p
        if h:
            text_html = text_html or h
    return text_plain, text_html


def _extract_body_from_message(msg: dict[str, Any]) -> str:
    payload = msg.get("payload") or {}
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if mime == "text/plain" and data:
        return _b64url_decode(data)
    if mime == "text/html" and data:
        return _b64url_decode(data)
    plain, html = _collect_bodies(payload)
    return plain or html or ""


def _parse_since(since_timestamp: str) -> datetime:
    """Parse ISO timestamp to timezone-aware UTC datetime."""
    s = since_timestamp.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime(1970, 1, 1, tzinfo=pytz.UTC)
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    else:
        dt = dt.astimezone(pytz.UTC)
    return dt


def _gmail_after_date(since_utc: datetime) -> str:
    """Gmail `after:` search uses YYYY/MM/DD (UTC calendar day)."""
    return f"{since_utc.year}/{since_utc.month:02d}/{since_utc.day:02d}"


def _list_query_for_since(since_utc: datetime) -> str:
    """
    Build Gmail search query for unread mail to fetch.

    We intentionally do NOT filter by message internalDate vs last_run
    after listing: Gmail `after:YYYY/MM/DD` already scopes by received date.
    A sub-day internalDate cutoff would drop same-day mail that arrived
    before the previous run (e.g. user marks an older message unread).
    """
    if since_utc.year < 2000:
        return "is:unread newer_than:365d"
    return f"is:unread after:{_gmail_after_date(since_utc)}"


def get_unread_since(since_timestamp: str) -> list[dict]:
    """
    Fetches unread emails for the mailbox.

    Returns list of raw email dicts with id, subject, body, from, to, cc, date.
    Uses Gmail query `is:unread after:YYYY/MM/DD` from the UTC calendar day of
    last_run (or `newer_than:365d` on first sync). Does not drop same-day mail
    by internalDate vs last_run — that was excluding valid unread messages.
    Returns [] on any error — never raises.
    """
    try:
        service = _get_gmail_service()
        if service is None:
            return []
        since_utc = _parse_since(since_timestamp)
        q = _list_query_for_since(since_utc)
        message_ids: list[str] = []
        page_token: str | None = None
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=q, pageToken=page_token, maxResults=100)
                .execute()
            )
            for m in resp.get("messages") or []:
                mid = m.get("id")
                if mid:
                    message_ids.append(mid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        results: list[dict] = []
        for mid in message_ids:
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=mid, format="full")
                    .execute()
                )
            except HttpError as e:
                print(f"[ERROR][gmail_client] messages.get failed: {e}")
                continue
            internal_date = int(msg.get("internalDate", "0"))
            headers = (msg.get("payload") or {}).get("headers") or []
            subject = _decode_mime_header(_header(headers, "Subject"))
            from_raw = _header(headers, "From")
            to_raw = _header(headers, "To")
            cc_raw = _header(headers, "Cc")
            body = _extract_body_from_message(msg)
            date_iso = datetime.fromtimestamp(
                internal_date / 1000.0, tz=pytz.UTC
            ).isoformat()
            results.append(
                {
                    "id": mid,
                    "subject": subject,
                    "body": body,
                    "from": from_raw,
                    "to": to_raw,
                    "cc": cc_raw,
                    "date": date_iso,
                }
            )
        return results
    except HttpError as e:
        print(f"[ERROR][gmail_client] Gmail API error: {e}")
        return []
    except Exception as e:
        print(f"[ERROR][gmail_client] get_unread_since failed: {e}")
        return []


def send_email(to: str, subject: str, body: str) -> bool:
    """Sends a plain-text email via Gmail API (users.messages.send). Returns True on success."""
    load_dotenv()
    to_addr = (to or "").strip()
    if not to_addr:
        print("[ERROR][gmail_client] send_email: empty recipient")
        return False
    svc = _get_gmail_service()
    if svc is None:
        print("[ERROR][gmail_client] send_email: no Gmail service")
        return False
    try:
        msg = EmailMessage()
        msg.set_content(body or "", charset="utf-8")
        msg["To"] = to_addr
        msg["Subject"] = subject or "(no subject)"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except HttpError as e:
        print(f"[ERROR][gmail_client] send_email HttpError: {e}")
        return False
    except Exception as e:
        print(f"[ERROR][gmail_client] send_email failed: {e}")
        return False
