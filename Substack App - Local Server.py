#!/usr/bin/env python3
"""
Substack App - Local Server.py — Serves the dashboard over http://localhost so you can
trigger pulls (full / recent-window / dashboard-only) with buttons
inside the dashboard itself, instead of a desktop shortcut or terminal.

HOW TO USE:
1. Run this once (or double-click "Substack App - Start Server.bat"):
     python "Substack App - Local Server.py"
   Leave this window running in the background — it's what listens for
   button clicks from the dashboard.
2. In Chrome, go to:
     http://localhost:8765/dashboard.html
   Bookmark this URL — that's the one you'll use from now on.
3. Use the Control Panel buttons at the top of the dashboard to trigger
   pulls. Progress prints live in this terminal window (and a short log
   is mirrored into the dashboard itself).

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
import webbrowser

PORT = 8765
OUTPUT_DIR = "output"
RUN_ALL_SCRIPT = "Substack App - Main.py"

_current_process = None
_process_lock = threading.Lock()
_log_lines = []
_log_lock = threading.Lock()
_last_mode_label = None


def _append_log(line):
    with _log_lock:
        _log_lines.append(line)
        del _log_lines[:-500]  # keep the last 500 lines only


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            with _log_lock:
                recent_log = list(_log_lines[-60:])
            self._send_json({
                "running": is_running(),
                "mode": _last_mode_label,
                "log": recent_log,
            })
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                body = {}
            mode = body.get("mode", "full")
            days = body.get("days")
            started, message = start_pull(mode, days)
            self._send_json({"started": started, "message": message}, 200 if started else 409)
        else:
            self.send_error(404)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(os.path.join(OUTPUT_DIR, "dashboard.html")):
        print(f"Note: {OUTPUT_DIR}/dashboard.html doesn't exist yet.")
        print("Run a pull first (a Control Panel button, once this server is up, or")
        print('python "Substack App - Main.py" directly) to generate it.')

    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/dashboard.html"
        print("=" * 50)
        print("Local dashboard server running")
        print("=" * 50)
        print(f"Open (and bookmark): {url}")
        print("Leave this window open while you use the dashboard.")
        print("Press Ctrl+C to stop.")
        print()
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
