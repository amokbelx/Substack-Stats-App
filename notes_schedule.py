"""
Scheduled Notes storage and safety rules.

Stores notes in output/scheduled_notes.json. Pure logic — no network calls.
The local server and tests both use this module.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

OUTPUT_DIR = "output"
SCHEDULE_PATH = os.path.join(OUTPUT_DIR, "scheduled_notes.json")

MAX_TEXT_LENGTH = 3000
MISSED_GRACE_MINUTES = 15
DEFAULT_DAILY_MAX = 10
DEFAULT_MIN_SECONDS_BETWEEN_POSTS = 300  # 5 minutes
MAX_AUTO_RETRIES = 2

STATUSES = (
    "draft",
    "scheduled",
    "posting",
    "posted",
    "failed",
    "missed",
    "cancelled",
)

# Allowed transitions for user/API actions (scheduler uses its own path).
ALLOWED_TRANSITIONS = {
    "draft": {"scheduled", "cancelled", "posting"},
    "scheduled": {"draft", "scheduled", "cancelled", "posting", "missed"},
    "posting": {"posted", "failed"},
    "posted": set(),
    "failed": {"scheduled", "draft", "cancelled", "posting"},
    "missed": {"scheduled", "draft", "cancelled", "posting"},
    "cancelled": {"scheduled", "draft"},
}

_file_lock = threading.RLock()

# Set by the scheduler / post-now when Substack returns an auth error.
# Cleared when the operator updates settings after fixing the cookie, or
# via clear_auth_blocked().
_auth_blocked = False
_auth_blocked_lock = threading.Lock()


def is_auth_blocked() -> bool:
    with _auth_blocked_lock:
        return _auth_blocked


def set_auth_blocked(value: bool = True) -> None:
    global _auth_blocked
    with _auth_blocked_lock:
        _auth_blocked = bool(value)


def clear_auth_blocked() -> None:
    set_auth_blocked(False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utc_now().isoformat()


def default_settings() -> dict:
    return {
        "dry_run": True,
        "daily_max": DEFAULT_DAILY_MAX,
        "min_seconds_between_posts": DEFAULT_MIN_SECONDS_BETWEEN_POSTS,
    }


def empty_store() -> dict:
    return {"settings": default_settings(), "notes": []}


def parse_datetime(value: Any) -> datetime:
    """Parse an ISO datetime and require it to be timezone-aware."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("scheduled_at must be an ISO datetime string")
    if dt.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone offset (e.g. 2026-10-02T09:00:00-04:00)")
    return dt


def validate_text(text: Any) -> str:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("text cannot be empty")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise ValueError(f"text cannot exceed {MAX_TEXT_LENGTH} characters")
    return cleaned


def validate_timezone_name(tz: Any) -> str:
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError("timezone must be a non-empty string (IANA name, e.g. America/New_York)")
    return tz.strip()


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)


def load_store(path: str = SCHEDULE_PATH) -> dict:
    with _file_lock:
        if not os.path.exists(path):
            return empty_store()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return empty_store()
        if not isinstance(data, dict):
            return empty_store()
        settings = default_settings()
        raw_settings = data.get("settings") or {}
        if isinstance(raw_settings, dict):
            if "dry_run" in raw_settings:
                settings["dry_run"] = bool(raw_settings["dry_run"])
            if "daily_max" in raw_settings:
                try:
                    settings["daily_max"] = max(1, int(raw_settings["daily_max"]))
                except (TypeError, ValueError):
                    pass
            if "min_seconds_between_posts" in raw_settings:
                try:
                    settings["min_seconds_between_posts"] = max(
                        0, int(raw_settings["min_seconds_between_posts"])
                    )
                except (TypeError, ValueError):
                    pass
        notes = data.get("notes") or []
        if not isinstance(notes, list):
            notes = []
        return {"settings": settings, "notes": notes}


def save_store(store: dict, path: str = SCHEDULE_PATH) -> None:
    with _file_lock:
        _ensure_parent(path)
        payload = {
            "settings": store.get("settings") or default_settings(),
            "notes": store.get("notes") or [],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)


def find_note(store: dict, note_id: str) -> Optional[dict]:
    for note in store.get("notes") or []:
        if note.get("id") == note_id:
            return note
    return None


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status and from_status == "scheduled":
        return True  # reschedule while still scheduled
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


def recover_interrupted_posting(store: dict) -> int:
    """On startup: any note stuck in 'posting' becomes failed — never auto-retry."""
    count = 0
    for note in store.get("notes") or []:
        if note.get("status") == "posting":
            note["status"] = "failed"
            note["last_error"] = "Interrupted while posting — needs review"
            count += 1
    return count


def mark_missed_notes(store: dict, now: Optional[datetime] = None) -> int:
    """Mark scheduled notes more than MISSED_GRACE_MINUTES overdue as missed."""
    now = now or _utc_now()
    cutoff = now - timedelta(minutes=MISSED_GRACE_MINUTES)
    count = 0
    for note in store.get("notes") or []:
        if note.get("status") != "scheduled":
            continue
        try:
            when = parse_datetime(note["scheduled_at"])
        except (ValueError, KeyError):
            continue
        if when <= cutoff:
            note["status"] = "missed"
            note["last_error"] = (
                f"Missed — server was off or asleep more than "
                f"{MISSED_GRACE_MINUTES} minutes past the scheduled time"
            )
            count += 1
    return count


def due_notes(store: dict, now: Optional[datetime] = None) -> list:
    """Return scheduled notes that are due but not yet in the missed window."""
    now = now or _utc_now()
    missed_cutoff = now - timedelta(minutes=MISSED_GRACE_MINUTES)
    due = []
    for note in store.get("notes") or []:
        if note.get("status") != "scheduled":
            continue
        try:
            when = parse_datetime(note["scheduled_at"])
        except (ValueError, KeyError):
            continue
        if when <= now and when > missed_cutoff:
            due.append(note)
    due.sort(key=lambda n: n.get("scheduled_at") or "")
    return due


def _posted_today_count(store: dict, now: Optional[datetime] = None) -> int:
    now = now or _utc_now()
    today = now.astimezone(timezone.utc).date()
    count = 0
    for note in store.get("notes") or []:
        if note.get("status") != "posted":
            continue
        posted_at = note.get("posted_at")
        if not posted_at:
            continue
        try:
            dt = parse_datetime(posted_at)
        except ValueError:
            continue
        if dt.astimezone(timezone.utc).date() == today:
            count += 1
    return count


def _last_auto_post_time(store: dict) -> Optional[datetime]:
    latest = None
    for note in store.get("notes") or []:
        if note.get("status") != "posted":
            continue
        if note.get("manual_post"):
            continue
        posted_at = note.get("posted_at")
        if not posted_at:
            continue
        try:
            dt = parse_datetime(posted_at)
        except ValueError:
            continue
        if latest is None or dt > latest:
            latest = dt
    return latest


def can_auto_post_now(store: dict, now: Optional[datetime] = None) -> tuple[bool, str]:
    """Check daily max and min spacing for automatic posts."""
    now = now or _utc_now()
    settings = store.get("settings") or default_settings()
    daily_max = int(settings.get("daily_max", DEFAULT_DAILY_MAX))
    min_gap = int(settings.get("min_seconds_between_posts", DEFAULT_MIN_SECONDS_BETWEEN_POSTS))
    if _posted_today_count(store, now) >= daily_max:
        return False, f"Daily automatic post limit reached ({daily_max})"
    last = _last_auto_post_time(store)
    if last is not None and min_gap > 0:
        elapsed = (now - last).total_seconds()
        if elapsed < min_gap:
            wait = int(min_gap - elapsed)
            return False, f"Waiting {wait}s before next automatic post (min gap {min_gap}s)"
    return True, ""


def create_note(
    store: dict,
    text: str,
    scheduled_at: str,
    timezone_name: str,
    status: str = "scheduled",
) -> dict:
    text = validate_text(text)
    when = parse_datetime(scheduled_at)
    timezone_name = validate_timezone_name(timezone_name)
    if status not in ("draft", "scheduled"):
        raise ValueError("new notes must start as draft or scheduled")
    note = {
        "id": str(uuid.uuid4()),
        "text": text,
        "scheduled_at": when.isoformat(),
        "timezone": timezone_name,
        "status": status,
        "attempts": 0,
        "last_error": None,
        "posted_at": None,
        "created_at": _now_iso(),
        "substack_note_id": None,
        "dry_run_post": False,
        "manual_post": False,
    }
    store.setdefault("notes", []).append(note)
    return note


def update_note(
    store: dict,
    note_id: str,
    *,
    text: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    timezone_name: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    note = find_note(store, note_id)
    if not note:
        raise KeyError(f"note not found: {note_id}")
    current = note.get("status")
    if current == "posted":
        raise ValueError("posted notes cannot be edited")
    if current == "posting":
        raise ValueError("note is currently posting — wait or restart the server")

    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        if not can_transition(current, status):
            raise ValueError(f"cannot change status from {current} to {status}")
        note["status"] = status
        if status in ("scheduled", "draft"):
            note["last_error"] = None

    if text is not None:
        note["text"] = validate_text(text)
    if scheduled_at is not None:
        when = parse_datetime(scheduled_at)
        note["scheduled_at"] = when.isoformat()
        # Rescheduling a missed/failed note back to scheduled is common.
        if note["status"] in ("missed", "failed") and status is None:
            if can_transition(note["status"], "scheduled"):
                note["status"] = "scheduled"
                note["last_error"] = None
        elif note["status"] == "cancelled" and status is None:
            pass
    if timezone_name is not None:
        note["timezone"] = validate_timezone_name(timezone_name)
    return note


def cancel_note(store: dict, note_id: str) -> dict:
    note = find_note(store, note_id)
    if not note:
        raise KeyError(f"note not found: {note_id}")
    current = note.get("status")
    if not can_transition(current, "cancelled"):
        raise ValueError(f"cannot cancel a note with status {current}")
    note["status"] = "cancelled"
    note["last_error"] = None
    return note


def delete_note(store: dict, note_id: str) -> dict:
    notes = store.get("notes") or []
    for i, note in enumerate(notes):
        if note.get("id") == note_id:
            if note.get("status") == "posting":
                raise ValueError("cannot delete a note that is currently posting")
            return notes.pop(i)
    raise KeyError(f"note not found: {note_id}")


def update_settings(store: dict, updates: dict) -> dict:
    settings = store.setdefault("settings", default_settings())
    if "dry_run" in updates:
        settings["dry_run"] = bool(updates["dry_run"])
    if "daily_max" in updates:
        try:
            settings["daily_max"] = max(1, int(updates["daily_max"]))
        except (TypeError, ValueError) as e:
            raise ValueError("daily_max must be a positive integer") from e
    if "min_seconds_between_posts" in updates:
        try:
            settings["min_seconds_between_posts"] = max(
                0, int(updates["min_seconds_between_posts"])
            )
        except (TypeError, ValueError) as e:
            raise ValueError("min_seconds_between_posts must be a non-negative integer") from e
    # Updating settings after fixing the cookie is the natural clear point.
    if updates.get("clear_auth_blocked"):
        clear_auth_blocked()
    return settings


def begin_posting(store: dict, note: dict) -> None:
    """Mark posting and bump attempts. Caller MUST save_store before network I/O."""
    current = note.get("status")
    if current == "posting":
        raise ValueError("note is already posting")
    if not can_transition(current, "posting"):
        raise ValueError(f"cannot post a note with status {current}")
    note["status"] = "posting"
    note["attempts"] = int(note.get("attempts") or 0) + 1
    note["last_error"] = None


def complete_posting(
    note: dict,
    *,
    dry_run: bool,
    substack_note_id: Optional[str] = None,
    manual: bool = False,
) -> None:
    note["status"] = "posted"
    note["posted_at"] = _now_iso()
    note["last_error"] = None
    note["dry_run_post"] = bool(dry_run)
    note["manual_post"] = bool(manual)
    note["substack_note_id"] = substack_note_id


def fail_posting(note: dict, error_message: str, *, auth_error: bool = False) -> None:
    # Never echo secrets — callers must sanitize before passing.
    msg = str(error_message or "Unknown error")
    if "cookie=" in msg.lower() or "substack.sid=" in msg.lower():
        msg = "Posting failed (details omitted to protect your session cookie)"
    note["status"] = "failed"
    note["last_error"] = msg
    if auth_error:
        set_auth_blocked(True)


def should_retry(note: dict) -> bool:
    """Auto-retry at most MAX_AUTO_RETRIES failed attempts (attempts already incremented)."""
    attempts = int(note.get("attempts") or 0)
    return attempts < MAX_AUTO_RETRIES and note.get("status") == "failed"


def public_note(note: dict) -> dict:
    """Return a JSON-safe copy with no secrets (notes never store the cookie)."""
    return {
        "id": note.get("id"),
        "text": note.get("text"),
        "scheduled_at": note.get("scheduled_at"),
        "timezone": note.get("timezone"),
        "status": note.get("status"),
        "attempts": note.get("attempts", 0),
        "last_error": note.get("last_error"),
        "posted_at": note.get("posted_at"),
        "created_at": note.get("created_at"),
        "substack_note_id": note.get("substack_note_id"),
        "dry_run_post": bool(note.get("dry_run_post")),
        "manual_post": bool(note.get("manual_post")),
    }


# Type for a poster callback: (text) -> dict with keys ok, auth_error, error, note_id
PosterFn = Callable[[str], dict]


def execute_post(
    store: dict,
    note_id: str,
    poster: PosterFn,
    *,
    dry_run: Optional[bool] = None,
    manual: bool = False,
    save_path: str = SCHEDULE_PATH,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Safe post flow:
      1. mark posting + save to disk
      2. dry-run: log and mark posted without network
      3. else call poster; on success mark posted; on failure mark failed
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    note = find_note(store, note_id)
    if not note:
        raise KeyError(f"note not found: {note_id}")

    settings = store.get("settings") or default_settings()
    if dry_run is None:
        dry_run = bool(settings.get("dry_run", True))

    if is_auth_blocked():
        raise RuntimeError(
            "Scheduler stopped: Substack session cookie looks expired. "
            "Re-save .substack_cookie.txt with the Chrome extension, then "
            "clear the auth block in Schedule settings."
        )

    begin_posting(store, note)
    save_store(store, save_path)

    if dry_run:
        _log(f"would have posted note {note_id}: {note.get('text', '')[:80]!r}")
        complete_posting(note, dry_run=True, substack_note_id=None, manual=manual)
        save_store(store, save_path)
        return {"ok": True, "dry_run": True, "note": public_note(note)}

    try:
        result = poster(note.get("text") or "")
    except Exception as e:  # noqa: BLE001 — convert to failed status
        fail_posting(note, f"Poster error: {e}")
        save_store(store, save_path)
        return {"ok": False, "dry_run": False, "note": public_note(note), "error": note["last_error"]}

    if not isinstance(result, dict):
        fail_posting(note, "Poster returned an unexpected result")
        save_store(store, save_path)
        return {"ok": False, "dry_run": False, "note": public_note(note), "error": note["last_error"]}

    if result.get("auth_error"):
        fail_posting(
            note,
            result.get("error")
            or "Substack session cookie expired — re-save it with the Chrome extension",
            auth_error=True,
        )
        save_store(store, save_path)
        return {
            "ok": False,
            "dry_run": False,
            "auth_error": True,
            "note": public_note(note),
            "error": note["last_error"],
        }

    if not result.get("ok"):
        fail_posting(note, result.get("error") or "Posting failed")
        save_store(store, save_path)
        return {"ok": False, "dry_run": False, "note": public_note(note), "error": note["last_error"]}

    complete_posting(
        note,
        dry_run=False,
        substack_note_id=result.get("note_id"),
        manual=manual,
    )
    save_store(store, save_path)
    _log(f"posted note {note_id}")
    return {"ok": True, "dry_run": False, "note": public_note(note)}


def run_scheduler_tick(
    store: dict,
    poster: PosterFn,
    *,
    save_path: str = SCHEDULE_PATH,
    now: Optional[datetime] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    One scheduler pass: recover is caller's job at startup.
    Mark missed, then try at most one due note if limits allow.
    """
    now = now or _utc_now()
    summary = {"missed": 0, "posted": 0, "skipped": None, "auth_blocked": is_auth_blocked()}

    summary["missed"] = mark_missed_notes(store, now)
    if summary["missed"]:
        save_store(store, save_path)

    if is_auth_blocked():
        summary["skipped"] = "auth_blocked"
        return summary

    ok_limits, reason = can_auto_post_now(store, now)
    if not ok_limits:
        summary["skipped"] = reason
        return summary

    due = due_notes(store, now)
    if not due:
        return summary

    # Only attempt notes that haven't exhausted retries in a weird state;
    # due_notes only returns status=scheduled, so attempts are for this post.
    note = due[0]
    # If a previous crash left attempts high but status was reset to scheduled
    # somehow, still allow — attempts only increment inside begin_posting.

    result = execute_post(
        store,
        note["id"],
        poster,
        manual=False,
        save_path=save_path,
        log=log,
    )
    if result.get("ok"):
        summary["posted"] = 1
    else:
        summary["skipped"] = result.get("error") or "post_failed"
        # Re-queue for retry: if under max attempts and not auth, put back to scheduled
        n = find_note(store, note["id"])
        if n and n.get("status") == "failed" and not result.get("auth_error"):
            if int(n.get("attempts") or 0) < MAX_AUTO_RETRIES:
                n["status"] = "scheduled"
                save_store(store, save_path)
                summary["skipped"] = f"will_retry: {n.get('last_error')}"
    return summary
