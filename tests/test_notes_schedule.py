#!/usr/bin/env python3
"""Unit tests for scheduled Notes storage, safety rules, and scheduler ticks."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

import notes_schedule as ns


def _aware(dt=None, **delta):
    base = dt or datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    if delta:
        base = base + timedelta(**delta)
    return base


class NotesScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "scheduled_notes.json")
        self.store = ns.empty_store()
        ns.clear_auth_blocked()

    def tearDown(self):
        ns.clear_auth_blocked()
        self.tmp.cleanup()

    def _create(self, text="Hello note", when=None, status="scheduled", tz="UTC"):
        when = when or _aware(hours=1)
        return ns.create_note(
            self.store,
            text=text,
            scheduled_at=when.isoformat(),
            timezone_name=tz,
            status=status,
        )

    def test_default_settings_dry_run_on(self):
        settings = ns.default_settings()
        self.assertTrue(settings["dry_run"])
        self.assertEqual(settings["daily_max"], 10)
        self.assertEqual(settings["min_seconds_between_posts"], 300)

    def test_create_and_roundtrip(self):
        note = self._create()
        ns.save_store(self.store, self.path)
        loaded = ns.load_store(self.path)
        self.assertEqual(len(loaded["notes"]), 1)
        self.assertEqual(loaded["notes"][0]["id"], note["id"])
        self.assertEqual(loaded["notes"][0]["text"], "Hello note")
        self.assertTrue(loaded["settings"]["dry_run"])

    def test_reject_naive_datetime(self):
        with self.assertRaises(ValueError):
            ns.create_note(
                self.store,
                text="x",
                scheduled_at="2026-10-02T09:00:00",
                timezone_name="UTC",
            )

    def test_reject_empty_and_long_text(self):
        with self.assertRaises(ValueError):
            self._create(text="   ")
        with self.assertRaises(ValueError):
            self._create(text="x" * (ns.MAX_TEXT_LENGTH + 1))

    def test_due_time_detection(self):
        now = _aware()
        due = self._create(when=now - timedelta(minutes=5))
        not_yet = self._create(text="later", when=now + timedelta(minutes=30))
        found = ns.due_notes(self.store, now=now)
        ids = [n["id"] for n in found]
        self.assertIn(due["id"], ids)
        self.assertNotIn(not_yet["id"], ids)

    def test_missed_notes_not_auto_posted(self):
        now = _aware()
        old = self._create(when=now - timedelta(minutes=20))
        recent = self._create(text="recent", when=now - timedelta(minutes=5))
        missed = ns.mark_missed_notes(self.store, now=now)
        self.assertEqual(missed, 1)
        self.assertEqual(old["status"], "missed")
        self.assertEqual(recent["status"], "scheduled")
        due = ns.due_notes(self.store, now=now)
        self.assertEqual([n["id"] for n in due], [recent["id"]])

    def test_double_post_prevention_saves_before_poster(self):
        note = self._create(when=_aware(minutes=-1))
        calls = {"poster": 0, "saw_posting_on_disk": False}

        def poster(text):
            calls["poster"] += 1
            loaded = ns.load_store(self.path)
            on_disk = ns.find_note(loaded, note["id"])
            calls["saw_posting_on_disk"] = on_disk is not None and on_disk["status"] == "posting"
            return {"ok": True, "note_id": "n-1"}

        # Force dry_run off for this call
        self.store["settings"]["dry_run"] = False
        result = ns.execute_post(
            self.store, note["id"], poster, dry_run=False, save_path=self.path
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls["poster"], 1)
        self.assertTrue(calls["saw_posting_on_disk"])
        self.assertEqual(note["status"], "posted")
        self.assertEqual(note["substack_note_id"], "n-1")

    def test_recover_interrupted_posting_never_retries(self):
        note = self._create()
        note["status"] = "posting"
        note["attempts"] = 1
        n = ns.recover_interrupted_posting(self.store)
        self.assertEqual(n, 1)
        self.assertEqual(note["status"], "failed")
        self.assertIn("needs review", note["last_error"])
        # Scheduler must not pick it as due
        self.assertEqual(ns.due_notes(self.store, now=_aware(hours=2)), [])

    def test_dry_run_skips_poster(self):
        note = self._create(when=_aware(minutes=-1))
        poster = mock.Mock(return_value={"ok": True, "note_id": "should-not-matter"})
        logs = []
        result = ns.execute_post(
            self.store,
            note["id"],
            poster,
            dry_run=True,
            save_path=self.path,
            log=logs.append,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        poster.assert_not_called()
        self.assertTrue(note["dry_run_post"])
        self.assertTrue(any("would have posted" in line for line in logs))

    def test_daily_limit_blocks_auto_post(self):
        now = _aware()
        self.store["settings"]["daily_max"] = 2
        self.store["settings"]["min_seconds_between_posts"] = 0
        for i in range(2):
            n = self._create(text=f"done {i}", when=now - timedelta(hours=2))
            n["status"] = "posted"
            n["posted_at"] = now.isoformat()
            n["manual_post"] = False
        pending = self._create(text="pending", when=now - timedelta(minutes=1))
        ok, reason = ns.can_auto_post_now(self.store, now=now)
        self.assertFalse(ok)
        self.assertIn("Daily", reason)

        poster = mock.Mock(return_value={"ok": True, "note_id": "x"})
        summary = ns.run_scheduler_tick(
            self.store, poster, save_path=self.path, now=now
        )
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(pending["status"], "scheduled")
        poster.assert_not_called()

    def test_min_gap_blocks_auto_post(self):
        now = _aware()
        self.store["settings"]["daily_max"] = 10
        self.store["settings"]["min_seconds_between_posts"] = 300
        prev = self._create(text="prev", when=now - timedelta(hours=1))
        prev["status"] = "posted"
        prev["posted_at"] = (now - timedelta(seconds=30)).isoformat()
        prev["manual_post"] = False
        self._create(text="next", when=now - timedelta(minutes=1))
        ok, reason = ns.can_auto_post_now(self.store, now=now)
        self.assertFalse(ok)
        self.assertIn("Waiting", reason)

    def test_status_transitions(self):
        note = self._create()
        ns.cancel_note(self.store, note["id"])
        self.assertEqual(note["status"], "cancelled")
        with self.assertRaises(ValueError):
            ns.cancel_note(self.store, note["id"])
        # Reschedule from cancelled via update to scheduled
        ns.update_note(
            self.store,
            note["id"],
            status="scheduled",
            scheduled_at=_aware(hours=3).isoformat(),
        )
        self.assertEqual(note["status"], "scheduled")

        note["status"] = "posted"
        with self.assertRaises(ValueError):
            ns.update_note(self.store, note["id"], text="nope")

    def test_auth_error_blocks_further_posts(self):
        note = self._create(when=_aware(minutes=-1))
        self.store["settings"]["dry_run"] = False

        def poster(text):
            return {
                "ok": False,
                "auth_error": True,
                "error": "Substack session cookie expired — re-save it with the Chrome extension",
            }

        result = ns.execute_post(
            self.store, note["id"], poster, dry_run=False, save_path=self.path
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("auth_error"))
        self.assertTrue(ns.is_auth_blocked())
        self.assertEqual(note["status"], "failed")

        other = self._create(text="other", when=_aware(minutes=-1))
        with self.assertRaises(RuntimeError):
            ns.execute_post(
                self.store, other["id"], poster, dry_run=False, save_path=self.path
            )

    def test_retry_then_fail(self):
        note = self._create(when=_aware(minutes=-1))
        self.store["settings"]["dry_run"] = False
        self.store["settings"]["min_seconds_between_posts"] = 0

        def bad(text):
            return {"ok": False, "error": "temporary glitch"}

        # First failure — scheduler puts back to scheduled for retry
        summary = ns.run_scheduler_tick(
            self.store, bad, save_path=self.path, now=_aware()
        )
        self.assertEqual(summary["posted"], 0)
        note = ns.find_note(self.store, note["id"])
        self.assertEqual(note["status"], "scheduled")
        self.assertEqual(note["attempts"], 1)

        # Second failure — attempts == MAX_AUTO_RETRIES, stays failed
        summary = ns.run_scheduler_tick(
            self.store, bad, save_path=self.path, now=_aware()
        )
        note = ns.find_note(ns.load_store(self.path), note["id"])
        # After 2nd attempt, attempts=2 which is NOT < MAX_AUTO_RETRIES(2), so stays failed
        self.assertEqual(note["attempts"], 2)
        self.assertEqual(note["status"], "failed")

    def test_delete_and_public_note_has_no_secrets(self):
        note = self._create()
        pub = ns.public_note(note)
        self.assertNotIn("cookie", pub)
        deleted = ns.delete_note(self.store, note["id"])
        self.assertEqual(deleted["id"], note["id"])
        self.assertIsNone(ns.find_note(self.store, note["id"]))

    def test_fail_posting_sanitizes_cookie_like_errors(self):
        note = self._create()
        ns.fail_posting(note, "server said cookie=substack.sid=abc123; bad")
        self.assertNotIn("abc123", note["last_error"])
        self.assertIn("protect", note["last_error"])

    def test_update_settings(self):
        ns.set_auth_blocked(True)
        settings = ns.update_settings(
            self.store, {"dry_run": False, "daily_max": 3, "clear_auth_blocked": True}
        )
        self.assertFalse(settings["dry_run"])
        self.assertEqual(settings["daily_max"], 3)
        self.assertFalse(ns.is_auth_blocked())

    def test_scheduler_tick_dry_run_posts_due_note(self):
        now = _aware()
        note = self._create(when=now - timedelta(minutes=2))
        self.store["settings"]["dry_run"] = True
        self.store["settings"]["min_seconds_between_posts"] = 0
        poster = mock.Mock()
        summary = ns.run_scheduler_tick(
            self.store, poster, save_path=self.path, now=now, log=lambda m: None
        )
        self.assertEqual(summary["posted"], 1)
        poster.assert_not_called()
        self.assertEqual(note["status"], "posted")
        self.assertTrue(note["dry_run_post"])


if __name__ == "__main__":
    unittest.main()
