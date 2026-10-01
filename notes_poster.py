"""
Post a Substack Note using the saved session cookie.

IMPORTANT: This module talks to an undocumented, unofficial Substack
endpoint that may change without notice. The real request is filled in
only after capturing a live browser POST from DevTools (see the Setup &
Usage Guide). Until then, post_note() returns a clear "not configured"
error — it never guesses a URL or payload.

Never log, print, or return the cookie value.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def _load_cookie() -> Optional[str]:
    """Load the session cookie the same way Main.py does. Returns None if missing."""
    # Direct read — mirrors Main.py's candidates without importing Main
    # (Main's filename has spaces, so it isn't a normal importable module).
    env_cookie = os.environ.get("SUBSTACK_COOKIE")
    if env_cookie and env_cookie.strip():
        return _cookie_from_raw(env_cookie)

    app_dir = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    candidates = (
        os.path.join(app_dir, ".substack_cookie.txt"),
        os.path.join(app_dir, "substack_cookie.txt"),
        os.path.join(home, ".substack_cookie.txt"),
        os.path.join(home, "substack_cookie.txt"),
        os.path.join(home, ".substack_cookie.txt.txt"),
    )
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            raw = _read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        cookie = _cookie_from_raw(raw)
        if cookie:
            return cookie
    return None


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    return data.decode("utf-8")


def _cookie_from_raw(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, dict):
            cookie = data.get("cookie")
            if isinstance(cookie, str) and cookie.strip():
                return cookie.strip()
            return None
    return text


def post_note(text: str) -> dict:
    """
    Post a Note to Substack.

    Returns a dict:
      {"ok": True, "note_id": "<id or None>"}
      {"ok": False, "error": "...", "auth_error": bool}

    NEVER include the cookie in the returned dict or in error strings.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Note text is empty", "auth_error": False}

    cookie = _load_cookie()
    if not cookie:
        return {
            "ok": False,
            "error": (
                "No Substack cookie found. Save .substack_cookie.txt with the "
                "Chrome extension, then try again."
            ),
            "auth_error": True,
        }

    # --- PLACEHOLDER -------------------------------------------------------
    # The real endpoint/payload must be filled in from a captured browser
    # request (DevTools → Network → Fetch/XHR → post a test Note → Copy as
    # cURL, with Cookie redacted before sharing).
    #
    # This is an undocumented, unofficial Substack endpoint and may change.
    # Do not invent a URL or body shape here.
    _ = cookie  # cookie will be used once the real request is wired in
    return {
        "ok": False,
        "error": (
            "Posting is not configured yet. Capture a real Note POST from "
            "Chrome DevTools (see the Setup & Usage Guide) and paste the "
            "redacted request so the notes_poster.py function can be completed. "
            "Keep Dry run ON until then."
        ),
        "auth_error": False,
        "not_configured": True,
    }
    # --- end placeholder ---------------------------------------------------


def _post_json(url: str, body: dict, cookie: str) -> dict:
    """
    Helper for the future real implementation.
    Sends JSON with the session cookie. Never logs cookie or response secrets.
    """
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Cookie": cookie,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {"ok": True, "note_id": None}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"ok": True, "note_id": None}
            note_id = None
            if isinstance(parsed, dict):
                note_id = (
                    parsed.get("id")
                    or parsed.get("note_id")
                    or (parsed.get("comment") or {}).get("id")
                )
                if note_id is not None:
                    note_id = str(note_id)
            return {"ok": True, "note_id": note_id}
    except HTTPError as e:
        if e.code in (401, 403):
            return {
                "ok": False,
                "auth_error": True,
                "error": (
                    "Substack rejected the session (HTTP "
                    f"{e.code}). Re-save .substack_cookie.txt with the Chrome extension."
                ),
            }
        return {
            "ok": False,
            "auth_error": False,
            "error": f"Substack returned HTTP {e.code} while posting the Note",
        }
    except URLError:
        return {
            "ok": False,
            "auth_error": False,
            "error": "Network error while posting the Note",
        }


if __name__ == "__main__":
    # Manual smoke check — never prints the cookie.
    result = post_note(sys.argv[1] if len(sys.argv) > 1 else "test")
    print(json.dumps({k: v for k, v in result.items()}, indent=2))
