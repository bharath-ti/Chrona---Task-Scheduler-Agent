"""Shared Google OAuth scopes for Gmail + Calendar (single token.json)."""

GOOGLE_OAUTH_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]
