#!/usr/bin/env python3
"""
Substack App - Local Server.py — Serves the dashboard over http://localhost so you can
trigger pulls (full / recent-window / dashboard-only) with buttons
inside the dashboard itself, instead of a desktop shortcut or terminal.

Also runs the Notes scheduler in the background while this window is open.
Scheduled Notes only auto-post while this process is running and the
computer is awake.

HOW TO USE:
1. Run this once (or double-click "Substack App - Start Server.bat"):
     python "Substack App - Local Server.py"
   Leave this window running in the background — it's what listens for
   button clicks from the dashboard and posts due Notes.
2. In Chrome, go to:
     http://localhost:8765/dashboard.html
   Bookmark this URL — that's the one you'll use from now on.
3. Use the Control Panel buttons at the top of the dashboard to trigger
   pulls. Progress prints live in this terminal window (and a short log
   is mirrored into the dashboard itself).
4. Use the Schedule tab to create Notes. Keep Dry run ON until posting
   is configured and you've tested it.

You still need to double-click something once per session to start this
server — a truly zero-click always-on setup would mean running this at
Windows startup, which is a further step you can ask about if you want
it later. For now: start this, then everything else is in-browser.

This only ever runs the exact same main script you already have, as a
subprocess — it doesn't duplicate any pull logic, just gives you a way
to trigger it from a browser button.
"""

import http.server
import socketserver
import subprocess
import threading
import json
import os
import sys
import time
import shutil
import webbrowser
from urllib.parse import urlparse

import notes_schedule
import notes_poster

PORT = 8765
OUTPUT_DIR = "output"
RUN_ALL_SCRIPT = "Substack App - Main.py"
SCHEDULER_INTERVAL_SECONDS = 30
RETRY_DELAY_SECONDS = 60

_current_process = None
_process_lock = threading.Lock()
_log_lines = []
_log_lock = threading.Lock()
_last_mode_label = None

_scheduler_thread = None
_scheduler_stop = threading.Event()
_scheduler_running = False
_scheduler_lock = threading.Lock()
_last_retry_at = {}  # note_id -> monotonic time of last failed attempt
_scheduler_log = []
_scheduler_log_lock = threading.Lock()


def _append_log(line):
    with _log_lock:
        _log_lines.append(line)
        del _log_lines[:-500]  # keep the last 500 lines only


def _sched_log(line):
    msg = f"[scheduler] {line}"
    print(msg, flush=True)
    _append_log(msg)
    with _scheduler_log_lock:
        _scheduler_log.append(msg)
        del _scheduler_log[:-100]


def _read_process_output(proc):
    for raw_line in proc.stdout:
        _append_log(raw_line.rstrip("\n"))
    proc.wait()
    _append_log(f"--- process finished (exit code {proc.returncode}) ---")


def is_running():
    with _process_lock:
        return _current_process is not None and _current_process.poll() is None


def start_pull(mode, days=None):
    """Start the main script as a subprocess with the right arguments for the
    requested mode. Returns (started: bool, message: str)."""
    global _current_process, _last_mode_label

    with _process_lock:
        if _current_process is not None and _current_process.poll() is None:
            return False, "A pull is already running — wait for it to finish first."

        cmd = [sys.executable, RUN_ALL_SCRIPT]
        if mode == "dashboard-only":
            cmd.append("--dashboard-only")
            label = "Dashboard only (no new data)"
        elif mode == "recent":
            if not days:
                return False, "Missing 'days' for a recent-window pull."
            cmd += ["--recent", str(days)]
            label = f"Recent window — last {days} days"
        elif mode == "full":
            label = "Full historical pull"
        else:
            return False, f"Unknown mode: {mode}"

        _log_lines.clear()
        _append_log(f"=== Starting: {label} ===")
        _last_mode_label = label

        try:
            _current_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=os.getcwd(),
            )
        except Exception as e:
            _append_log(f"[!] Failed to start: {e}")
            return False, f"Failed to start: {e}"

        threading.Thread(target=_read_process_output, args=(_current_process,), daemon=True).start()
        return True, f"Started: {label}"


def sync_dashboard_assets():
    """Copy Dashboard.js / Dashboard.css into output/ so Schedule UI updates apply."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for asset in ("Substack App - Dashboard.css", "Substack App - Dashboard.js"):
        src = asset
        dst = os.path.join(OUTPUT_DIR, asset)
        if os.path.exists(src):
            try:
                shutil.copyfile(src, dst)
            except OSError as e:
                print(f"[!] Could not copy {asset}: {e}")


def _startup_schedule_recovery():
    store = notes_schedule.load_store()
    n = notes_schedule.recover_interrupted_posting(store)
    if n:
        notes_schedule.save_store(store)
        _sched_log(f"Marked {n} interrupted posting note(s) as failed — needs review")
    missed = notes_schedule.mark_missed_notes(store)
    if missed:
        notes_schedule.save_store(store)
        _sched_log(f"Marked {missed} overdue note(s) as missed")


def _scheduler_loop():
    global _scheduler_running
    with _scheduler_lock:
        _scheduler_running = True
    _sched_log("Notes scheduler started (checks about every 30 seconds)")
    try:
        while not _scheduler_stop.is_set():
            try:
                store = notes_schedule.load_store()
                due = notes_schedule.due_notes(store)
                if due:
                    top_id = due[0].get("id")
                    last = _last_retry_at.get(top_id)
                    if last is not None and (time.monotonic() - last) < RETRY_DELAY_SECONDS:
                        missed = notes_schedule.mark_missed_notes(store)
                        if missed:
                            notes_schedule.save_store(store)
                            _sched_log(f"Marked {missed} note(s) missed")
                    else:
                        before_attempts = {
                            n.get("id"): int(n.get("attempts") or 0)
                            for n in (store.get("notes") or [])
                        }
                        summary = notes_schedule.run_scheduler_tick(
                            store, notes_poster.post_note, log=_sched_log
                        )
                        store_after = notes_schedule.load_store()
                        for n in store_after.get("notes") or []:
                            nid = n.get("id")
                            after_attempts = int(n.get("attempts") or 0)
                            if after_attempts > before_attempts.get(nid, 0):
                                if n.get("status") in ("failed", "scheduled"):
                                    _last_retry_at[nid] = time.monotonic()
                        if summary.get("posted"):
                            _sched_log("Posted 1 due note this tick")
                        elif summary.get("missed"):
                            _sched_log(f"Marked {summary['missed']} note(s) missed")
                else:
                    missed = notes_schedule.mark_missed_notes(store)
                    if missed:
                        notes_schedule.save_store(store)
                        _sched_log(f"Marked {missed} note(s) missed")
            except Exception as e:  # noqa: BLE001
                _sched_log(f"Tick error: {e}")
            _scheduler_stop.wait(SCHEDULER_INTERVAL_SECONDS)
    finally:
        with _scheduler_lock:
            _scheduler_running = False
        _sched_log("Notes scheduler stopped")


def start_scheduler():
    global _scheduler_thread
    _startup_schedule_recovery()
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, name="notes-scheduler", daemon=True)
    _scheduler_thread.start()


def scheduler_is_running():
    with _scheduler_lock:
        return _scheduler_running


def _read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise ValueError("Request body must be JSON")


def _schedule_status_payload():
    store = notes_schedule.load_store()
    settings = store.get("settings") or notes_schedule.default_settings()
    notes = [notes_schedule.public_note(n) for n in store.get("notes") or []]
    notes.sort(key=lambda n: n.get("scheduled_at") or "")
    with _scheduler_log_lock:
        recent = list(_scheduler_log[-40:])
    return {
        "notes": notes,
        "settings": settings,
        "scheduler_running": scheduler_is_running(),
        "dry_run": bool(settings.get("dry_run", True)),
        "auth_blocked": notes_schedule.is_auth_blocked(),
        "max_text_length": notes_schedule.MAX_TEXT_LENGTH,
        "scheduler_log": recent,
        "warning": (
            "Notes only auto-post while this server window is open and your "
            "computer is awake. Closing the window, sleeping the PC, or "
            "losing power will skip due Notes (they become Missed after "
            "15 minutes)."
        ),
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=OUTPUT_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # keep the terminal clean — pull output already prints there

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            with _log_lock:
                recent_log = list(_log_lines[-60:])
            self._send_json({
                "running": is_running(),
                "mode": _last_mode_label,
                "log": recent_log,
            })
        elif path == "/api/schedule":
            self._send_json(_schedule_status_payload())
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            try:
                body = _read_json_body(self)
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
                return
            mode = body.get("mode", "full")
            days = body.get("days")
            started, message = start_pull(mode, days)
            self._send_json({"started": started, "message": message}, 200 if started else 409)
            return

        if path == "/api/schedule":
            try:
                body = _read_json_body(self)
                store = notes_schedule.load_store()
                note = notes_schedule.create_note(
                    store,
                    text=body.get("text"),
                    scheduled_at=body.get("scheduled_at"),
                    timezone_name=body.get("timezone") or body.get("timezone_name") or "UTC",
                    status=body.get("status") or "scheduled",
                )
                notes_schedule.save_store(store)
                self._send_json({"ok": True, "note": notes_schedule.public_note(note)})
            except (ValueError, TypeError) as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/schedule/settings":
            try:
                body = _read_json_body(self)
                store = notes_schedule.load_store()
                settings = notes_schedule.update_settings(store, body)
                notes_schedule.save_store(store)
                if body.get("clear_auth_blocked"):
                    _sched_log("Auth block cleared by user")
                self._send_json({
                    "ok": True,
                    "settings": settings,
                    "auth_blocked": notes_schedule.is_auth_blocked(),
                })
            except (ValueError, TypeError) as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            return

        # /api/schedule/<id>/cancel|delete|post-now
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "schedule":
            note_id = parts[2]
            action = parts[3]
            store = notes_schedule.load_store()
            try:
                if action == "cancel":
                    note = notes_schedule.cancel_note(store, note_id)
                    notes_schedule.save_store(store)
                    self._send_json({"ok": True, "note": notes_schedule.public_note(note)})
                    return
                if action == "delete":
                    note = notes_schedule.delete_note(store, note_id)
                    notes_schedule.save_store(store)
                    self._send_json({"ok": True, "deleted": notes_schedule.public_note(note)})
                    return
                if action == "post-now":
                    if notes_schedule.is_auth_blocked():
                        self._send_json({
                            "ok": False,
                            "auth_error": True,
                            "error": (
                                "Posting is paused because the Substack cookie looks expired. "
                                "Re-save .substack_cookie.txt, then clear the auth warning in Schedule."
                            ),
                        }, 403)
                        return
                    result = notes_schedule.execute_post(
                        store,
                        note_id,
                        notes_poster.post_note,
                        manual=True,
                        log=_sched_log,
                    )
                    status = 200 if result.get("ok") else 400
                    self._send_json(result, status)
                    return
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
                return
            except (ValueError, RuntimeError) as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
                return

        self.send_error(404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "schedule":
            note_id = parts[2]
            try:
                body = _read_json_body(self)
                store = notes_schedule.load_store()
                tz_value = None
                if "timezone" in body or "timezone_name" in body:
                    tz_value = body.get("timezone") or body.get("timezone_name")
                note = notes_schedule.update_note(
                    store,
                    note_id,
                    text=body.get("text") if "text" in body else None,
                    scheduled_at=body.get("scheduled_at") if "scheduled_at" in body else None,
                    timezone_name=tz_value,
                    status=body.get("status") if "status" in body else None,
                )
                notes_schedule.save_store(store)
                self._send_json({"ok": True, "note": notes_schedule.public_note(note)})
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
            except (ValueError, TypeError) as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            return
        self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "schedule":
            note_id = parts[2]
            try:
                store = notes_schedule.load_store()
                note = notes_schedule.delete_note(store, note_id)
                notes_schedule.save_store(store)
                self._send_json({"ok": True, "deleted": notes_schedule.public_note(note)})
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            return
        self.send_error(404)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    sync_dashboard_assets()
    if not os.path.exists(os.path.join(OUTPUT_DIR, "dashboard.html")):
        print(f"Note: {OUTPUT_DIR}/dashboard.html doesn't exist yet.")
        print("Run a pull first (a Control Panel button, once this server is up, or")
        print('python "Substack App - Main.py" directly) to generate it.')

    start_scheduler()

    # Allow reuse of the port after a quick restart (Windows/Linux).
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/dashboard.html"
        print("=" * 50)
        print("Local dashboard server running")
        print("=" * 50)
        print(f"Open (and bookmark): {url}")
        print("Leave this window open while you use the dashboard.")
        print("Notes scheduler is running in the background.")
        print("Press Ctrl+C to stop.")
        print()
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping…")
            _scheduler_stop.set()
            print("Stopped.")


if __name__ == "__main__":
    main()
