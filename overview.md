# CURSOR PROJECT CONTEXT — Personalized Task Scheduler Agent
> **Read this entire file before writing a single line of code.**
> This is the authoritative specification for every module, every function signature,
> every data schema, and every design decision in this project.

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Core Philosophy & Rules](#2-core-philosophy--rules)
3. [Folder Structure](#3-folder-structure)
4. [Environment & Configuration](#4-environment--configuration)
5. [Data Schemas](#5-data-schemas)
6. [Module M1 — Background Watcher](#6-module-m1--background-watcher)
7. [Module M2 — AI Task Extractor](#7-module-m2--ai-task-extractor)
8. [Module M3 — Dedup & Priority Scorer](#8-module-m3--dedup--priority-scorer)
9. [Module M4 — Slack Approval Gate](#9-module-m4--slack-approval-gate)
10. [Module M5 — Calendar Scheduler](#10-module-m5--calendar-scheduler)
11. [Module M6 — Morning Digest](#11-module-m6--morning-digest)
12. [Main Orchestrator](#12-main-orchestrator)
13. [Utility Helpers](#13-utility-helpers)
14. [Error Handling Rules](#14-error-handling-rules)
15. [Testing Guide](#15-testing-guide)
16. [Full Pipeline Data Flow](#16-full-pipeline-data-flow)

---

## 1. PROJECT OVERVIEW

### What this agent does
This is a **fully autonomous, background-running Python agent** that:
1. Watches the user's Gmail inbox every 5 minutes, 24/7
2. Reads every qualifying email and meeting transcript
3. Uses **GPT-4o** to extract only tasks assigned to the user (Bharath)
4. Deduplicates tasks across sources and scores them by priority
5. Sends a **Slack DM** requesting approval for high-priority tasks (from VPs, clients)
6. Auto-schedules approved/low-priority tasks as **Google Calendar events**
7. Sends a **morning digest email at 8 AM** summarizing everything done overnight

### The core value proposition
By the time Bharath wakes up at 8 AM, every task from overnight emails and meetings is:
- Already extracted and understood
- Prioritized by sender importance and urgency
- Blocked as a time slot on Google Calendar
- Summarized in a single digest email

**Zero inbox time. Zero calendar management. Zero missed tasks.**

### Owner
- **Name:** Bharath
- **Role:** Intern
- **Stakeholder/VP:** Arlief
- **Timezone:** Asia/Kolkata (IST, UTC+5:30)

---

## 2. CORE PHILOSOPHY & RULES

These rules apply to **every file in this project**. Never violate them.

### Code rules
- **Python 3.11+** only. No other languages.
- **Every external API call** (OpenAI, Gmail, Slack, Google Calendar) must be wrapped in `try/except`. On failure: log the error with `print(f"[ERROR] ...")` and return a safe default (empty list, None, False).
- **Never crash the pipeline.** If M2 fails on one email, skip it and continue to the next. The agent must keep running.
- **Every function has a docstring** explaining what it takes in and what it returns.
- **Load all secrets from `.env`** using `python-dotenv`. Never hardcode API keys.
- **All datetimes are timezone-aware.** Use `pytz` with `Asia/Kolkata` as the default timezone. Never use naive datetime objects.
- **Atomic file writes for JSON state.** Write to a temp file first, then rename, to prevent corruption if the process is killed mid-write.

### Design rules
- **One file per module.** Do not put M1 and M2 logic in the same file.
- **Modules communicate via return values only.** M1 returns a list, M2 takes that list. No global state between modules.
- **task_store.json is the single source of truth** for all task state. Every module reads from and writes to this file.
- **people_config.json is read-only at runtime.** It is never modified by the agent.
- **DEMO_MODE** — if `DEMO_MODE=true` in `.env`, the M4 approval gate auto-approves all tasks without waiting for Slack response. This is for demo purposes only.

### What this agent does NOT do
- It does NOT modify or delete existing calendar events — only creates new ones
- It does NOT reply to emails on the user's behalf
- It does NOT store full email bodies to disk (only task titles and snippets)
- It does NOT send emails other than the morning digest

---

## 3. FOLDER STRUCTURE

```
task-scheduler-agent/
│
├── main.py                        # Orchestrator — runs the schedule loops
│
├── modules/
│   ├── __init__.py
│   ├── m1_watcher.py              # Gmail polling + email filtering
│   ├── m2_extractor.py            # GPT-4o task extraction
│   ├── m3_scorer.py               # Dedup + priority scoring
│   ├── m4_approval.py             # Slack approval gate
│   ├── m5_scheduler.py            # Google Calendar slot finder + event creator
│   └── m6_digest.py               # Morning digest email builder + sender
│
├── utils/
│   ├── __init__.py
│   ├── gmail_client.py            # Gmail API wrapper (read + send)
│   ├── calendar_client.py         # Google Calendar API wrapper
│   ├── slack_client.py            # Slack WebClient wrapper
│   └── file_store.py              # JSON read/write helpers (atomic writes)
│
├── config/
│   └── people_config.json         # Sender roles and priority weights
│
├── data/
│   ├── task_store.json            # Runtime task state (cleared after digest)
│   └── last_run.json              # Timestamp of last Gmail fetch
│
├── .env                           # All secrets — never commit this
├── .env.example                   # Template — safe to commit
├── .gitignore                     # Must include .env and data/*.json
├── requirements.txt               # All pip dependencies
└── README.md                      # Setup instructions
```

---

## 4. ENVIRONMENT & CONFIGURATION

### .env file (all required keys)
```env
# OpenAI
OPENAI_API_KEY=sk-...

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_USER_ID=U...          # Your Slack user ID (for DMs)

# Google (OAuth credentials path)
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json
GOOGLE_CALENDAR_ID=primary

# Agent config
YOUR_EMAIL=bharath@company.com
YOUR_NAME=Bharath
TIMEZONE=Asia/Kolkata
WORKING_HOURS_START=9          # 9 AM
WORKING_HOURS_END=20           # 8 PM
DIGEST_TIME=08:00              # 8 AM daily

# Demo mode (set to true to bypass Slack approval wait)
DEMO_MODE=false
```

### .env.example (commit this, not .env)
```env
OPENAI_API_KEY=sk-your-key-here
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_SIGNING_SECRET=your-secret-here
SLACK_USER_ID=your-slack-user-id
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json
GOOGLE_CALENDAR_ID=primary
YOUR_EMAIL=your@email.com
YOUR_NAME=YourName
TIMEZONE=Asia/Kolkata
WORKING_HOURS_START=9
WORKING_HOURS_END=20
DIGEST_TIME=08:00
DEMO_MODE=false
```

### requirements.txt
```
openai>=1.0.0
schedule>=1.2.0
pytz>=2024.1
slack-bolt>=1.18.0
slack-sdk>=3.27.0
python-dotenv>=1.0.0
google-api-python-client>=2.120.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
```

### config/people_config.json schema
```json
{
  "people": [
    {
      "email": "arlief@company.com",
      "name": "Arlief",
      "role": "VP",
      "priority_weight": 10
    },
    {
      "email": "client@acme.com",
      "name": "John",
      "role": "client",
      "priority_weight": 9
    },
    {
      "email": "manager@company.com",
      "name": "Manager",
      "role": "manager",
      "priority_weight": 8
    },
    {
      "email": "peer@company.com",
      "name": "Ravi",
      "role": "peer",
      "priority_weight": 5
    }
  ]
}
```

**Role priority weights (hardcoded fallback):**
| Role | Weight |
|------|--------|
| VP | 10 |
| client | 9 |
| manager | 8 |
| peer | 5 |
| unknown | 3 |

---

## 5. DATA SCHEMAS

### Task object (the core data structure used everywhere)
```python
{
    "id": "uuid4-string",                    # e.g. "a1b2c3d4-..."
    "title": "Complete Q3 report",           # Short action title, max 8 words
    "description": "Full context...",        # Everything needed to do the task
    "deadline": "2026-05-13T23:59:00+05:30", # ISO 8601 with timezone, or null
    "estimated_minutes": 120,                # Always an integer
    "source": "email",                       # "email" or "transcript"
    "sources": ["email", "transcript"],      # All sources (after dedup merge)
    "sender": "arlief@company.com",
    "sender_name": "Arlief",
    "sender_role": "VP",                     # VP/client/manager/peer/unknown
    "sender_weight": 10,                     # From people_config
    "urgency": "critical",                   # critical/high/medium/low
    "raw_snippet": "Bharath please complete the Q3...",  # Exact source phrase
    "priority_score": 9.3,                   # Calculated by M3
    "needs_approval": True,                  # Set by M3
    "status": "pending_approval",            # See status values below
    "calendar_event_id": null,               # Set by M5 after scheduling
    "slack_message_ts": null,                # Set by M4 after sending DM
    "seen_count": 1,                         # Incremented on dedup merge
    "created_at": "2026-05-13T23:35:00+05:30",
    "updated_at": "2026-05-13T23:35:00+05:30"
}
```

**Task status values (lifecycle):**
```
extracted        → Just created by M2, not yet scored
pending_approval → Sent to Slack, waiting for user response
approved         → User approved via Slack
dismissed        → User dismissed via Slack
scheduled        → Calendar event created by M5
unschedulable    → No free slot found before deadline
auto_scheduled   → Scheduled without approval (low priority)
```

### task_store.json schema
```json
{
  "tasks": [
    { ...task object... },
    { ...task object... }
  ],
  "last_cleared": "2026-05-13T08:00:00+05:30"
}
```

### last_run.json schema
```json
{
  "last_processed_at": "2026-05-13T23:30:00+05:30"
}
```

---

## 6. MODULE M1 — BACKGROUND WATCHER

**File:** `modules/m1_watcher.py`
**Purpose:** Entry point of the pipeline. Polls Gmail every 5 minutes, filters noise, returns qualifying emails ready for M2.
**Trigger:** Called by `main.py` every 5 minutes via `schedule`
**Dependencies:** `utils/gmail_client.py`, `utils/file_store.py`, `config/people_config.json`, `data/last_run.json`

### Blocklists (hardcoded in module)
```python
BLOCKLIST_SENDERS = [
    "noreply@", "no-reply@", "notifications@", "alerts@",
    "donotreply@", "mailer@", "newsletter@", "digest@",
    "linkedin.com", "medium.com", "twitter.com", "github.com"
]

BLOCKLIST_SUBJECTS = [
    "newsletter", "unsubscribe", "job alert", "linkedin digest",
    "weekly digest", "your receipt", "order confirmation",
    "verification code", "otp", "invoice from"
]

TRANSCRIPT_SIGNALS = [
    "transcript", "meeting notes", "meeting summary",
    "read.ai", "otter.ai", "zoom recording", "teams meeting notes"
]
```

### Function signatures

```python
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
```

```python
def _load_people_config() -> dict:
    """Loads config/people_config.json. Returns {"people": []} on error."""
```

```python
def _get_sender_context(sender_email: str, people: list) -> tuple[str, str, int]:
    """
    Looks up sender in people list.
    Returns: (role, name, weight) — defaults to ("unknown", sender_email, 3)
    """
```

```python
def _is_noise(subject: str, sender_email: str, to_field: str, your_email: str) -> bool:
    """
    Returns True if email should be skipped.
    Checks: blocklist senders, blocklist subjects, CC-only (not in TO field).
    """
```

```python
def _is_transcript(subject: str, sender_email: str, body: str) -> bool:
    """Returns True if email is a meeting transcript based on TRANSCRIPT_SIGNALS."""
```

```python
def _update_last_run() -> None:
    """Writes current UTC timestamp to data/last_run.json."""
```

### Key implementation notes
- Use `gmail_client.get_unread_since(timestamp)` to fetch emails
- Strip HTML from body using a simple regex or `html.parser` — plain text only
- The `to_field` check: if `YOUR_EMAIL` is not in the `To:` header (only in `CC:`), skip it
- After fetching, call `_update_last_run()` regardless of whether emails were found
- Log: `print(f"[M1] Fetched {len(raw)} emails, {len(filtered)} passed filters")`

---

## 7. MODULE M2 — AI TASK EXTRACTOR

**File:** `modules/m2_extractor.py`
**Purpose:** The brain of the agent. Sends each qualifying email to GPT-4o and extracts structured task objects assigned specifically to Bharath.
**Trigger:** Called by `main.py` for each email returned by M1
**Dependencies:** `openai` SDK, `.env` (OPENAI_API_KEY, YOUR_NAME)
**Model:** `gpt-4o` — do NOT use gpt-3.5-turbo or gpt-4o-mini

### The extraction prompt

**System prompt (exact text to use):**
```
You are a task extraction assistant for {YOUR_NAME}.

Your job: Read the email or meeting transcript below and extract ONLY the tasks that are explicitly assigned to {YOUR_NAME}. Ignore tasks assigned to others, general announcements, FYI items, and tasks where the assignment is ambiguous.

Return a JSON object with a single key "tasks" containing an array of task objects.
If no tasks are found for {YOUR_NAME}, return {"tasks": []}.

Each task object MUST follow this exact schema:
{
  "title": "short action title, maximum 8 words, starts with a verb",
  "description": "complete context needed to actually do this task",
  "deadline": "ISO 8601 datetime string with timezone OR null if not mentioned",
  "estimated_minutes": integer (your best estimate if not explicitly stated),
  "urgency": "critical" | "high" | "medium" | "low",
  "raw_snippet": "the exact phrase from the source that assigns this task"
}

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
```

**User message format:**
```
Sender: {sender_name} ({sender_email}) — Role: {sender_role}
Subject: {subject}
Received: {timestamp}

---
{body}
```

### Function signatures

```python
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
```

```python
def _build_messages(email: dict) -> list[dict]:
    """Builds the messages array for the OpenAI API call."""
```

```python
def _parse_response(response_text: str, email: dict) -> list[dict]:
    """
    Parses the JSON response from GPT-4o into task dicts.
    Adds: source, sender, sender_name, sender_role, sender_weight from email.
    Returns [] if JSON is invalid or "tasks" key missing.
    """
```

### Critical implementation details
- **Always use `response_format={"type": "json_object"}`** — this forces GPT-4o to return valid JSON. Without this, the pipeline can crash on malformed output.
- Set `temperature=0` for consistent, deterministic extraction
- Set `max_tokens=1500` — enough for 5-6 tasks with full descriptions
- The response will be a string like `'{"tasks": [...]}'` — parse with `json.loads()`
- Log: `print(f"[M2] Extracted {len(tasks)} tasks from email: {email['subject'][:50]}")`

### Example API call structure
```python
response = client.chat.completions.create(
    model="gpt-4o",
    response_format={"type": "json_object"},
    temperature=0,
    max_tokens=1500,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message}
    ]
)
result = json.loads(response.choices[0].message.content)
tasks = result.get("tasks", [])
```

---

## 8. MODULE M3 — DEDUP & PRIORITY SCORER

**File:** `modules/m3_scorer.py`
**Purpose:** Takes the raw task list from M2, removes duplicates across sources, scores every task using a weighted formula, and marks which ones need Slack approval.
**Trigger:** Called by `main.py` after all emails in a batch are processed by M2
**Dependencies:** `utils/file_store.py`, `data/task_store.json`, `pytz`

### Priority scoring formula
```python
priority_score = (
    (sender_weight        * 0.35) +   # Range: 0-10
    (urgency_score        * 0.30) +   # Range: 0-10
    (deadline_proximity   * 0.25) +   # Range: 0-10
    (duration_score       * 0.10)     # Range: 0-10
)
# Final score range: 0.0 to 10.0
```

**Score lookup tables:**
```python
URGENCY_SCORES = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 1
}

def deadline_proximity_score(deadline_iso: str | None) -> int:
    # null/no deadline → 1
    # > 7 days away   → 2
    # 3-7 days away   → 4
    # 1-3 days away   → 7
    # 12-24 hours     → 8
    # < 12 hours      → 10

def duration_score(estimated_minutes: int) -> int:
    # > 120 min → 10
    # 60-120    → 7
    # 30-60     → 5
    # < 30      → 3
```

### Approval threshold logic
```python
needs_approval = (
    priority_score >= 7.0
    OR sender_role in ["VP", "client"]
    OR hours_until_deadline < 12
)
```

### Deduplication algorithm
```python
def _word_overlap(title_a: str, title_b: str) -> float:
    """
    Returns overlap ratio between 0.0 and 1.0.
    Uses lowercase word sets, ignores stopwords (the, a, an, is, to, for, of).
    Threshold: > 0.70 = duplicate.
    """
    stopwords = {"the", "a", "an", "is", "to", "for", "of", "and", "in", "on", "at"}
    words_a = set(title_a.lower().split()) - stopwords
    words_b = set(title_b.lower().split()) - stopwords
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))
```

**Merge rules when duplicate found:**
- Keep the title from the FIRST occurrence
- Keep the STRICTEST (earliest) deadline
- Combine `sources` lists: `["email", "transcript"]`
- Keep the HIGHEST `sender_weight`
- Increment `seen_count`
- Update `updated_at`

### Function signatures

```python
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
```

```python
def _assign_ids_and_defaults(tasks: list[dict]) -> list[dict]:
    """Adds id (uuid4), status='extracted', created_at, updated_at, seen_count=1."""
```

```python
def _score_task(task: dict) -> float:
    """Calculates and returns the priority_score for a single task."""
```

---

## 9. MODULE M4 — SLACK APPROVAL GATE

**File:** `modules/m4_approval.py`
**Purpose:** Sends a formatted Slack DM for each high-priority task requesting the user's approval before it gets scheduled. Handles approve/dismiss responses.
**Trigger:** Called by `main.py` for tasks where `needs_approval=True`
**Dependencies:** `slack-sdk`, `utils/slack_client.py`, `utils/file_store.py`, `.env`

### DEMO_MODE behaviour
```python
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# If DEMO_MODE is True:
# - send_approval_request() sends the Slack message BUT immediately
#   sets status="approved" without waiting
# - Log: print("[M4] DEMO_MODE: auto-approving task:", task['title'])
```

### Slack message format (Block Kit)
The message must contain these blocks in order:
1. **Header block:** "New high-priority task detected"
2. **Section block:** Task details as a field list (title, from, source, deadline, estimated time, proposed slot)
3. **Actions block:** Three buttons — "Approve" (primary/green), "Edit time" (default), "Dismiss" (danger/red)

**Callback IDs for buttons:**
- Approve button action_id: `"approve_task"`
- Edit button action_id: `"edit_task_time"`
- Dismiss button action_id: `"dismiss_task"`
- Include `task_id` in each button's `value` field

### Proposed slot calculation
Before sending the message, M4 calls `m5_scheduler.find_next_free_slot(task)` to get a proposed time. Display it in the message as "9:00 AM – 11:00 AM tomorrow". If no slot found, display "No free slot found before deadline ⚠️".

### Timeout handling
```python
APPROVAL_TIMEOUT_MINUTES = 30

def check_pending_timeouts() -> None:
    """
    Called by main.py every 5 minutes.
    For tasks with status="pending_approval" older than 30 minutes:
    - Keep status as "pending_approval" (do NOT auto-approve)
    - Add "timed_out": True to task
    - Log: print(f"[M4] Timeout: task {task['id']} will appear in digest as pending")
    """
```

### Function signatures

```python
def send_approval_request(task: dict) -> bool:
    """
    Sends a Slack DM to the user requesting approval for a task.

    Args:
        task: Full task dict from M3

    Returns:
        True if message sent successfully, False on error.

    Side effects:
        - Updates task status to "pending_approval" in task_store.json
        - Stores slack_message_ts on the task object
        - In DEMO_MODE: immediately sets status to "approved"
    """
```

```python
def handle_approve(task_id: str) -> None:
    """Sets task status to 'approved' in task_store.json. Called by Slack webhook."""
```

```python
def handle_dismiss(task_id: str) -> None:
    """Sets task status to 'dismissed' in task_store.json. Called by Slack webhook."""
```

```python
def _build_slack_blocks(task: dict, proposed_slot: str) -> list[dict]:
    """Builds and returns the Slack Block Kit blocks list for the approval message."""
```

---

## 10. MODULE M5 — CALENDAR SCHEDULER

**File:** `modules/m5_scheduler.py`
**Purpose:** Finds a conflict-free time slot in Google Calendar and creates a calendar event with full task context. Called after approval (or directly for auto-approved tasks).
**Trigger:** Called by `main.py` after a task is approved or auto-approved
**Dependencies:** `utils/calendar_client.py`, `utils/file_store.py`, `pytz`, `.env`

### Slot-finding algorithm (step by step)
```
1. Get search window: now → task.deadline (or now+7days if no deadline)
2. Fetch all existing calendar events in that window via Google Calendar API
3. Build list of busy_windows: [(start_dt, end_dt), ...] sorted by start
4. Define working_hours: WORKING_HOURS_START to WORKING_HOURS_END from .env
5. required_duration = task.estimated_minutes + 30  (30 min safety buffer)
6. Iterate through each day in the search window:
   a. Set day_start = max(now, today at WORKING_HOURS_START)
   b. Set day_end = today at WORKING_HOURS_END
   c. For each gap between busy_windows within [day_start, day_end]:
      - If gap_duration >= required_duration: return (gap_start, gap_start + estimated_minutes)
7. If no slot found: return None
```

### Calendar event details
```python
event_body = {
    "summary": task["title"],
    "description": (
        f"From: {task['sender_name']} ({task['sender_role']}) "
        f"via {task['source']}\n"
        f"Deadline: {task['deadline'] or 'Not specified'}\n"
        f"Priority: {task['urgency'].capitalize()} · Score {task['priority_score']:.1f}\n"
        f"Estimated: {task['estimated_minutes']} minutes\n\n"
        f"Source snippet:\n\"{task['raw_snippet']}\"\n\n"
        f"Scheduled by: Task Scheduler Agent"
    ),
    "start": {"dateTime": slot_start.isoformat(), "timeZone": TIMEZONE},
    "end":   {"dateTime": slot_end.isoformat(),   "timeZone": TIMEZONE},
    "colorId": _urgency_to_color(task["urgency"]),
    "reminders": {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 15}]
    }
}
```

**Color ID mapping:**
```python
URGENCY_COLORS = {
    "critical": "11",   # Tomato (red)
    "high":     "5",    # Banana (yellow)
    "medium":   "9",    # Blueberry (dark blue)
    "low":      "8"     # Graphite (gray)
}
```

### No-slot warning
```python
# If find_slot() returns None:
# 1. Update task status to "unschedulable" in task_store
# 2. Send a Slack DM warning:
#    "⚠️ No free slot found for: {task['title']}
#     Deadline: {task['deadline']}
#     Your calendar is fully booked. Please reschedule manually."
```

### Function signatures

```python
def find_and_book_slot(task: dict) -> dict | None:
    """
    Finds a free calendar slot and creates a Google Calendar event.

    Args:
        task: Approved task dict with estimated_minutes and deadline

    Returns:
        The created Google Calendar event dict, or None if no slot found.

    Side effects:
        - Creates a real Google Calendar event
        - Updates task status to "scheduled" or "unschedulable" in task_store.json
        - Stores calendar_event_id on the task
        - Sends Slack warning if unschedulable
    """
```

```python
def find_next_free_slot(task: dict) -> str | None:
    """
    Returns a human-readable string of the next free slot for this task.
    Used by M4 to show proposed slot in Slack message.
    Returns None if no slot found.
    Example return: "9:00 AM – 11:00 AM tomorrow"
    """
```

```python
def _get_busy_windows(start_dt, end_dt) -> list[tuple]:
    """Fetches calendar events and returns list of (start, end) datetime tuples."""
```

```python
def _find_free_slot(busy_windows, deadline_dt, required_minutes) -> tuple | None:
    """Core algorithm. Returns (slot_start, slot_end) or None."""
```

---

## 11. MODULE M6 — MORNING DIGEST

**File:** `modules/m6_digest.py`
**Purpose:** Triggered every morning at 8 AM. Compiles all tasks processed in the last 24 hours into a single clear email and sends it to the user. Then clears task_store.json.
**Trigger:** Scheduled by `main.py` via `schedule.every().day.at("08:00")`
**Dependencies:** `utils/gmail_client.py`, `utils/file_store.py`, `pytz`

### Email structure (plain text)

```
Subject: Your day is planned — {n} tasks scheduled · {date}

Good morning {YOUR_NAME} — here's what your agent did overnight.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCHEDULED TODAY ({count} tasks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[{urgency.upper()}]  {title}
         {time_slot}  ·  from {sender_name} ({sender_role})
         via {source}

... (one block per task, sorted by calendar start time)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEEDS YOUR APPROVAL ({count} tasks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• {title}  ·  from {sender_name}  ·  deadline {deadline}
  → Open Slack to approve

... (one line per pending task)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UNSCHEDULABLE ({count} tasks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• {title}  ·  No free slot found before {deadline}
  → Please schedule manually

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTO-DISMISSED ({count} emails)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• {n} newsletters, {m} notifications, {k} promotional emails

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated by Task Scheduler Agent · {datetime}
```

### Function signatures

```python
def send_morning_digest() -> bool:
    """
    Main entry point for M6.
    Loads task_store.json, categorizes all tasks, builds email body,
    sends via Gmail, clears task_store.json.

    Returns:
        True if email sent successfully, False on error.
        IMPORTANT: Even if email fails, still clear task_store to prevent
        the same tasks appearing in tomorrow's digest.
    """
```

```python
def _categorize_tasks(tasks: list[dict]) -> dict:
    """
    Returns:
    {
        "scheduled": [...tasks with status="scheduled", sorted by calendar start],
        "pending": [...tasks with status="pending_approval"],
        "unschedulable": [...tasks with status="unschedulable"],
        "dismissed": [...tasks with status="dismissed"]
    }
    """
```

```python
def _build_digest_body(categories: dict, dismissed_email_count: int) -> str:
    """Builds and returns the full plain-text digest email body string."""
```

```python
def _clear_task_store() -> None:
    """Resets task_store.json to {"tasks": [], "last_cleared": now_iso}"""
```

---

## 12. MAIN ORCHESTRATOR

**File:** `main.py`
**Purpose:** Wires all 6 modules together. Manages the two scheduled jobs (5-min pipeline, 8AM digest). Provides `--test` flag for single-run testing.

### Complete orchestrator logic

```python
def run_pipeline():
    """
    The main 5-minute pipeline. Called by schedule every 5 minutes.
    Full sequence:
    1. M1: Fetch and filter emails
    2. M2: Extract tasks from each email (loop)
    3. M3: Dedup and score all new tasks
    4. M4: Send Slack approval for needs_approval=True tasks
    5. M5: Schedule approved and auto-approved tasks
    6. M4: Check for timed-out pending approvals
    Log summary at the end.
    """
```

### Schedule setup
```python
import schedule
import time

# Run pipeline every 5 minutes
schedule.every(5).minutes.do(run_pipeline)

# Run digest every day at 08:00
schedule.every().day.at(os.getenv("DIGEST_TIME", "08:00")).do(send_morning_digest)

# Main loop
while True:
    schedule.run_pending()
    time.sleep(60)  # Check every 60 seconds
```

### --test flag (argparse)
```python
# python main.py --test
# Runs run_pipeline() exactly ONCE, then exits.
# Does NOT start the schedule loop.
# Perfect for development and demo.

# python main.py --digest
# Runs send_morning_digest() once, then exits.
# For testing the digest without waiting for 8 AM.
```

### Startup log
```
print("=" * 50)
print("Task Scheduler Agent starting...")
print(f"Polling Gmail every 5 minutes")
print(f"Morning digest scheduled at {DIGEST_TIME}")
print(f"User: {YOUR_NAME} ({YOUR_EMAIL})")
print(f"Timezone: {TIMEZONE}")
print(f"DEMO_MODE: {DEMO_MODE}")
print("=" * 50)
```

---

## 13. UTILITY HELPERS

### utils/file_store.py
```python
def load_task_store() -> dict:
    """Loads data/task_store.json. Returns {"tasks": []} if file doesn't exist."""

def save_task_store(store: dict) -> None:
    """Atomically saves to data/task_store.json (write temp → rename)."""

def update_task(task_id: str, updates: dict) -> None:
    """Finds task by id in task_store and applies updates dict. Saves file."""

def get_task(task_id: str) -> dict | None:
    """Returns task dict by id, or None if not found."""

def load_last_run() -> str:
    """Returns last_processed_at ISO string from last_run.json. Returns epoch if missing."""

def save_last_run(timestamp: str) -> None:
    """Saves timestamp to data/last_run.json."""
```

### utils/gmail_client.py
```python
def get_unread_since(since_timestamp: str) -> list[dict]:
    """
    Fetches unread emails received after since_timestamp.
    Returns list of raw email dicts with id, subject, body, from, to, date.
    Uses Gmail API with query: f"is:unread after:{unix_timestamp}"
    """

def send_email(to: str, subject: str, body: str) -> bool:
    """Sends email via Gmail API. Returns True on success."""
```

### utils/calendar_client.py
```python
def get_events(start_dt, end_dt) -> list[dict]:
    """Returns all calendar events between start and end datetimes."""

def create_event(event_body: dict) -> dict:
    """Creates a calendar event. Returns the created event dict."""
```

### utils/slack_client.py
```python
def send_dm(user_id: str, text: str = None, blocks: list = None) -> str | None:
    """
    Sends a DM to user_id.
    Returns message timestamp (ts) on success, None on failure.
    """

def update_message(channel: str, ts: str, text: str, blocks: list = None) -> None:
    """Updates an existing Slack message (used to mark approved/dismissed)."""
```

---

## 14. ERROR HANDLING RULES

Every module MUST follow these patterns:

### Pattern 1 — External API calls
```python
try:
    result = external_api_call(...)
    return result
except Exception as e:
    print(f"[ERROR][ModuleName] API call failed: {e}")
    return safe_default  # [] or None or False
```

### Pattern 2 — JSON file operations
```python
try:
    with open(path, 'r') as f:
        return json.load(f)
except FileNotFoundError:
    return default_value
except json.JSONDecodeError as e:
    print(f"[ERROR] Corrupt JSON at {path}: {e}")
    return default_value
```

### Pattern 3 — Atomic file write
```python
import tempfile, os

def atomic_write_json(path: str, data: dict) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)  # Atomic on POSIX systems
```

### Pattern 4 — Pipeline resilience
```python
# In main.py run_pipeline():
for email in emails:
    try:
        tasks = extract_tasks(email)
    except Exception as e:
        print(f"[ERROR][M2] Failed on email {email['subject']}: {e}")
        tasks = []  # Skip this email, continue pipeline
    all_tasks.extend(tasks)
```

---

## 15. TESTING GUIDE

### Smoke test — run after each module is built
```bash
# Test M2 in isolation (most important test)
python -c "
from modules.m2_extractor import extract_tasks
email = {
    'body': 'Hi Bharath, please complete the Q3 report by tonight. Thanks, Arlief',
    'subject': 'Urgent: Q3 Report',
    'sender_email': 'arlief@company.com',
    'sender_name': 'Arlief',
    'sender_role': 'VP',
    'sender_weight': 10,
    'timestamp': '2026-05-13T22:00:00+05:30',
    'is_transcript': False
}
result = extract_tasks(email)
print('Tasks found:', len(result))
print('First task:', result[0] if result else 'NONE')
assert len(result) >= 1, 'M2 FAILED: no tasks extracted'
assert result[0]['urgency'] == 'critical', 'M2 FAILED: wrong urgency'
print('M2 PASSED')
"
```

```bash
# Full pipeline test
python main.py --test

# Expected console output:
# [M1] Fetched N emails, M passed filters
# [M2] Extracted K tasks from email: ...
# [M3] Scored N tasks, M need approval
# [M4] Sent approval request for: ...
# [M5] Scheduled: ... at 9:00 AM - 11:00 AM
# Pipeline complete: N emails → K tasks → M scheduled
```

```bash
# Test digest generation
python main.py --digest
```

### What a successful full run looks like
1. Console shows `[M1] Fetched 1 emails, 1 passed filters`
2. Console shows `[M2] Extracted 2 tasks from email: Urgent: Q3 Report`
3. Console shows `[M3] Scored 2 tasks, 2 need approval (score >= 7.0)`
4. **Slack DM arrives** with task details and Approve/Edit/Dismiss buttons
5. Google Calendar shows **new event created** with task details in description
6. Console shows `Pipeline complete: 1 emails → 2 tasks → 2 scheduled`

---

## 16. FULL PIPELINE DATA FLOW

```
Gmail Inbox
    │
    ▼
M1: fetch_and_filter_emails()
    │  Returns: [email_dict, ...]
    │  Each has: body, subject, sender_email, sender_role, sender_weight,
    │            timestamp, is_transcript
    ▼
M2: extract_tasks(email) — called for each email
    │  Returns: [partial_task_dict, ...]
    │  Each has: title, description, deadline, estimated_minutes,
    │            urgency, raw_snippet, source, sender_*
    ▼
    [flatten all task lists]
    │
    ▼
M3: dedup_and_score(all_new_tasks)
    │  Returns: [full_task_dict, ...] sorted by priority_score desc
    │  Each has: all M2 fields + id, priority_score, needs_approval,
    │            status="extracted", seen_count, created_at
    │  Side effect: saves to task_store.json
    ▼
    [split into two paths]
    │
    ├── needs_approval=True ──→ M4: send_approval_request(task)
    │                              Side effect: status → "pending_approval"
    │                              Waits for Slack response (or DEMO_MODE skip)
    │                              On approve: status → "approved"
    │                              On dismiss: status → "dismissed"
    │                                   │
    │                                   ▼ (approved)
    │                              M5: find_and_book_slot(task)
    │                                   Side effect: status → "scheduled"
    │                                               calendar_event_id set
    │
    └── needs_approval=False ──→ M5: find_and_book_slot(task)
                                     status → "auto_scheduled"

Every day at 08:00 AM:
M6: send_morning_digest()
    Reads task_store.json
    Sends digest email
    Clears task_store.json
```

---

## FINAL NOTES FOR CURSOR

1. **Build modules in this order:** M2 → M1 → M3 → M5 → M4 → M6 → main.py
   M2 first because it's the hardest and most important — validate it works before building anything else.

2. **Never skip the try/except.** Every external call (OpenAI, Gmail, Slack, Calendar) has a try/except with a safe default return.

3. **The `--test` flag is your best friend.** Every time you build a new module, wire it into main.py and run `python main.py --test`. Fix errors immediately before moving on.

4. **DEMO_MODE=true** bypasses the Slack approval wait. Always have this available for demos.

5. **The GPT-4o prompt is sacred.** Do not change the system prompt wording. It is carefully crafted for accurate task ownership detection. If extraction seems wrong, adjust the user message format, not the system prompt.

6. **Timezone is Asia/Kolkata (IST).** Every datetime must be timezone-aware. Use `pytz.timezone("Asia/Kolkata")`. Never use naive datetimes.

7. **When in doubt about a function signature, refer back to Section 5 (Data Schemas).** The task object schema is the contract between all modules.

---

*End of Cursor Project Context Document*
*Version: 1.0 · Project: Personalized Task Scheduler Agent · Owner: Bharath*