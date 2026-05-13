"""JSON persistence helpers for runtime data files."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LAST_RUN_PATH = DATA_DIR / "last_run.json"
TASK_STORE_PATH = DATA_DIR / "task_store.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically (temp file then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(data, tmp, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_task_store() -> dict:
    """Loads data/task_store.json. Returns {"tasks": []} if file doesn't exist."""
    try:
        if not TASK_STORE_PATH.is_file():
            return {"tasks": [], "last_cleared": None}
        with open(TASK_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"tasks": [], "last_cleared": None}
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        out: dict[str, Any] = {"tasks": tasks}
        if "last_cleared" in data:
            out["last_cleared"] = data["last_cleared"]
        else:
            out["last_cleared"] = None
        return out
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR][file_store] load_task_store failed: {e}")
        return {"tasks": [], "last_cleared": None}


def save_task_store(store: dict) -> None:
    """Atomically saves to data/task_store.json (write temp → rename)."""
    try:
        if not isinstance(store, dict):
            print("[ERROR][file_store] save_task_store: store must be a dict")
            return
        tasks = store.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        payload: dict[str, Any] = {"tasks": tasks}
        if "last_cleared" in store:
            payload["last_cleared"] = store["last_cleared"]
        _atomic_write_json(TASK_STORE_PATH, payload)
    except Exception as e:
        print(f"[ERROR][file_store] save_task_store failed: {e}")


def get_task(task_id: str) -> dict | None:
    """Returns task dict by id, or None if not found."""
    try:
        store = load_task_store()
        for t in store.get("tasks", []):
            if isinstance(t, dict) and t.get("id") == task_id:
                return t
        return None
    except Exception as e:
        print(f"[ERROR][file_store] get_task failed: {e}")
        return None


def update_task(task_id: str, updates: dict) -> None:
    """Finds task by id in task_store and applies updates dict. Saves file."""
    try:
        store = load_task_store()
        tasks = store.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        found = False
        for i, t in enumerate(tasks):
            if isinstance(t, dict) and t.get("id") == task_id:
                if not isinstance(updates, dict):
                    break
                tasks[i] = {**t, **updates}
                found = True
                break
        if not found:
            print(f"[ERROR][file_store] update_task: no task with id={task_id!r}")
            return
        store["tasks"] = tasks
        save_task_store(store)
    except Exception as e:
        print(f"[ERROR][file_store] update_task failed: {e}")


def load_last_run() -> str:
    """
    Returns last_processed_at ISO string from last_run.json.
    Returns epoch UTC if missing or corrupt.
    """
    try:
        if not LAST_RUN_PATH.is_file():
            return "1970-01-01T00:00:00+00:00"
        with open(LAST_RUN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("last_processed_at")
        if not isinstance(ts, str) or not ts.strip():
            return "1970-01-01T00:00:00+00:00"
        return ts.strip()
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR][file_store] load_last_run failed: {e}")
        return "1970-01-01T00:00:00+00:00"


def save_last_run(timestamp: str) -> None:
    """Saves last_processed_at to data/last_run.json."""
    try:
        _atomic_write_json(LAST_RUN_PATH, {"last_processed_at": timestamp})
    except Exception as e:
        print(f"[ERROR][file_store] save_last_run failed: {e}")
