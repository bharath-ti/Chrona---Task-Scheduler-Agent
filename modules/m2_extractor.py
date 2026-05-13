"""M2 — GPT-4o task extraction from M1 email dicts."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pytz
from dotenv import load_dotenv
from openai import OpenAI

# System prompt wording is fixed by project spec (overview.md); only
# {YOUR_NAME} and {current_datetime} are substituted.
_SYSTEM_PROMPT_TEMPLATE = """You are a task extraction assistant for {YOUR_NAME}.

Your job: Read the email or meeting transcript below and extract ONLY the tasks that are explicitly assigned to {YOUR_NAME}. Ignore tasks assigned to others, general announcements, FYI items, and tasks where the assignment is ambiguous.

Return a JSON object with a single key "tasks" containing an array of task objects.
If no tasks are found for {YOUR_NAME}, return {{"tasks": []}}.

Each task object MUST follow this exact schema:
{{
  "title": "short action title, maximum 8 words, starts with a verb",
  "description": "complete context needed to actually do this task",
  "deadline": "ISO 8601 datetime string with timezone OR null if not mentioned",
  "estimated_minutes": integer (your best estimate if not explicitly stated),
  "urgency": "critical" | "high" | "medium" | "low",
  "raw_snippet": "the exact phrase from the source that assigns this task"
}}

Urgency classification rules:
- critical: "tonight", "ASAP", "urgent", "immediately", "blocker", "before EOD today"
- high: "tomorrow", "soon", "priority", "important", "need this by [specific date]"
- medium: "this week", "when you can", "please do", "follow up", "by end of week"
- low: no time pressure, general request, nice-to-have

Estimation rules:
- If duration is explicitly mentioned ("takes about 2 hours"), use that exact value
- For reports/analysis: 90-180 minutes
- For presentations/decks: 60-120 minutes
- For review tasks: 30-60 minutes
- For quick responses/updates: 15-30 minutes
- For meetings/calls: use the scheduled duration

Today's date and time: {current_datetime}
User's name: {YOUR_NAME}
"""

_URGENCY_ALLOWED = frozenset({"critical", "high", "medium", "low"})


def _build_messages(email: dict) -> list[dict]:
    """Builds the messages array for the OpenAI API call."""
    load_dotenv()
    your_name = (os.getenv("YOUR_NAME") or "").strip() or "User"
    tz_name = os.getenv("TIMEZONE", "Asia/Kolkata")
    tz = pytz.timezone(tz_name)
    current_datetime = datetime.now(tz).isoformat()
    system_content = _SYSTEM_PROMPT_TEMPLATE.format(
        YOUR_NAME=your_name,
        current_datetime=current_datetime,
    )
    sender_name = str(email.get("sender_name") or "")
    sender_email = str(email.get("sender_email") or "")
    sender_role = str(email.get("sender_role") or "")
    subject = str(email.get("subject") or "")
    timestamp = str(email.get("timestamp") or "")
    body = str(email.get("body") or "")
    user_content = (
        f"Sender: {sender_name} ({sender_email}) — Role: {sender_role}\n"
        f"Subject: {subject}\n"
        f"Received: {timestamp}\n"
        f"\n---\n"
        f"{body}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _parse_response(response_text: str, email: dict) -> list[dict]:
    """
    Parses the JSON response from GPT-4o into task dicts.
    Adds: source, sender, sender_name, sender_role, sender_weight from email.
    Returns [] if JSON is invalid or "tasks" key missing.
    """
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"[ERROR][M2] Invalid JSON from model: {e}")
        return []
    if not isinstance(data, dict):
        print("[ERROR][M2] Model response is not a JSON object")
        return []
    raw_tasks = data.get("tasks")
    if raw_tasks is None:
        print("[ERROR][M2] Missing 'tasks' key in model response")
        return []
    if not isinstance(raw_tasks, list):
        print("[ERROR][M2] 'tasks' is not an array")
        return []

    source = "transcript" if email.get("is_transcript") else "email"
    sender = str(email.get("sender_email") or "")
    sender_name = str(email.get("sender_name") or "")
    sender_role = str(email.get("sender_role") or "")
    try:
        sender_weight = int(email.get("sender_weight", 3))
    except (TypeError, ValueError):
        sender_weight = 3

    out: list[dict] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        description = str(item.get("description", "")).strip()
        raw_snippet = str(item.get("raw_snippet", "")).strip()

        deadline_raw = item.get("deadline", None)
        deadline: str | None
        if deadline_raw is None or deadline_raw == "null":
            deadline = None
        else:
            deadline = str(deadline_raw).strip() or None

        em = item.get("estimated_minutes", 30)
        try:
            estimated_minutes = int(em)
        except (TypeError, ValueError):
            estimated_minutes = 30
        if estimated_minutes < 1:
            estimated_minutes = 1

        urg = str(item.get("urgency", "medium")).strip().lower()
        if urg not in _URGENCY_ALLOWED:
            urg = "medium"

        out.append(
            {
                "title": title,
                "description": description,
                "deadline": deadline,
                "estimated_minutes": estimated_minutes,
                "urgency": urg,
                "raw_snippet": raw_snippet,
                "source": source,
                "sender": sender,
                "sender_name": sender_name,
                "sender_role": sender_role,
                "sender_weight": sender_weight,
            }
        )
    return out


def extract_tasks(email: dict) -> list[dict]:
    """
    Sends a single email dict to GPT-4o and extracts tasks assigned to the user.

    Args:
        email: dict from M1 with keys: body, subject, sender_email, sender_name,
               sender_role, sender_weight, timestamp, is_transcript

    Returns:
        List of partial task dicts (without id, status, priority_score — M3 adds those).
        Each dict has: title, description, deadline, estimated_minutes, urgency,
                       raw_snippet, source, sender, sender_name, sender_role, sender_weight
        Returns [] if no tasks found or on API error.
    """
    try:
        load_dotenv()
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            print("[ERROR][M2] OPENAI_API_KEY is not set")
            return []

        messages = _build_messages(email)
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1500,
            messages=messages,
        )
        if not response.choices:
            print("[ERROR][M2] No completion choices returned")
            tasks = []
        else:
            choice = response.choices[0]
            content = choice.message.content
            if not content:
                print("[ERROR][M2] Empty model response")
                tasks = []
            else:
                tasks = _parse_response(content, email)

        subj = str(email.get("subject") or "")[:50]
        print(f"[M2] Extracted {len(tasks)} tasks from email: {subj}")
        return tasks
    except Exception as e:
        print(f"[ERROR][M2] extract_tasks failed: {e}")
        return []
