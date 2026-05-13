"""Google Calendar API: list busy windows and create events (OAuth, same token as Gmail)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.google_scopes import GOOGLE_OAUTH_SCOPES

logger = logging.getLogger(__name__)

SCOPES: list[str] = GOOGLE_OAUTH_SCOPES


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _get_credentials() -> Credentials | None:
    creds: Credentials | None = None
    token_path = _project_root() / "token.json"
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets = _project_root() / "credentials.json"
            if not secrets.exists():
                logger.warning("credentials.json not found; Calendar disabled.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_calendar_service():
    creds = _get_credentials()
    if creds is None:
        return None
    return build("calendar", "v3", credentials=creds)


def event_bounds_utc(ev: dict[str, Any], tz_name: str) -> tuple[datetime, datetime] | None:
    """Parse a Calendar API event into (start, end) in UTC, or None if unparseable."""
    from zoneinfo import ZoneInfo

    zi = ZoneInfo(tz_name)

    def parse_field(field: dict[str, Any]) -> datetime:
        if "dateTime" in field:
            raw = field["dateTime"]
            if raw.endswith("Z"):
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=zi).astimezone(timezone.utc)
            return dt.astimezone(timezone.utc)
        if "date" in field:
            d = datetime.fromisoformat(field["date"]).date()
            return datetime(d.year, d.month, d.day, tzinfo=zi).astimezone(timezone.utc)
        raise ValueError("no date in field")

    try:
        st = ev.get("start") or {}
        en = ev.get("end") or {}
        s = parse_field(st)
        e = parse_field(en)
        if "date" in (ev.get("start") or {}) and "date" in (ev.get("end") or {}):
            e = e - timedelta(seconds=1)
        return s, e
    except Exception:
        return None


def get_events(
    time_min: datetime,
    time_max: datetime,
    calendar_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return raw event dicts in [time_min, time_max]."""
    svc = get_calendar_service()
    if svc is None:
        return []
    cal_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
    if time_min.tzinfo is None:
        time_min = time_min.replace(tzinfo=timezone.utc)
    if time_max.tzinfo is None:
        time_max = time_max.replace(tzinfo=timezone.utc)
    tmin = time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    tmax = time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "calendarId": cal_id,
                "timeMin": tmin,
                "timeMax": tmax,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = svc.events().list(**kwargs).execute()
            out.extend(resp.get("items", []) or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out
    except HttpError as e:
        logger.warning("Calendar list failed: %s", e)
        return []


def create_event(event_body: dict[str, Any], calendar_id: str | None = None) -> dict[str, Any] | None:
    svc = get_calendar_service()
    if svc is None:
        return None
    cal_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
    try:
        created = (
            svc.events()
            .insert(calendarId=cal_id, body=event_body, sendUpdates="all")
            .execute()
        )
        return created if isinstance(created, dict) else None
    except HttpError as e:
        logger.warning("Calendar create failed: %s", e)
        return None
