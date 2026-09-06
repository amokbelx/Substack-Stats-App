#!/usr/bin/env python3
"""Unit tests for cookie-file parsing and first-run config loading."""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAIN_PATH = ROOT / "Substack App - Main.py"


def load_session_helpers(config_path, cookie_path):
    """Load the session-bundle helpers from Main.py without running setup."""
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_app_dir",
        "normalize_publication",
        "cookie_file_candidates",
        "read_cookie_text",
        "parse_session_bundle",
        "read_session_bundle",
        "pick_publication_from_profile",
        "fetch_identity_from_cookie",
        "get_cookie",
        "save_config",
        "load_config",
        "run_setup_wizard",
    }
    module = ast.Module(body=[], type_ignores=[])
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            module.body.append(node)
    ast.fix_missing_locations(module)

    namespace = {
        "os": os,
        "json": json,
        "__file__": str(MAIN_PATH),
        "CONFIG_PATH": config_path,
        "COOKIE_FILE_PATH": cookie_path,
    }
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    return namespace


class ParseSessionBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_session_helpers("unused-config.json", "unused-cookie.txt")
        cls.parse = staticmethod(cls.ns["parse_session_bundle"])
        cls.normalize = staticmethod(cls.ns["normalize_publication"])

    def test_legacy_raw_cookie(self):
        raw = "substack.sid=abc123; other=xyz"
        self.assertEqual(
            self.parse(raw),
            {"cookie": raw, "publication": None, "user_id": None},
        )

    def test_json_bundle(self):
        bundle = {
            "publication": "example",
            "user_id": "123456789",
            "cookie": "substack.sid=abc123; other=xyz",
        }
        self.assertEqual(self.parse(json.dumps(bundle, indent=2)), bundle)

    def test_json_numeric_user_id_and_url_publication(self):
        raw = json.dumps({
            "publication": "https://Example.substack.com/about",
            "user_id": 42,
            "cookie": " sid=1 ",
        })
        self.assertEqual(
            self.parse(raw),
            {"cookie": "sid=1", "publication": "Example", "user_id": "42"},
        )

    def test_json_subdomain_alias(self):
        raw = json.dumps({
            "subdomain": "my-pub",
            "user_id": "99",
            "cookie": "a=b",
        })
        parsed = self.parse(raw)
        self.assertEqual(parsed["publication"], "my-pub")
        self.assertEqual(parsed["user_id"], "99")
        self.assertEqual(parsed["cookie"], "a=b")

    def test_invalid_json_is_treated_as_cookie(self):
        raw = "{not json"
        self.assertEqual(
            self.parse(raw),
            {"cookie": raw, "publication": None, "user_id": None},
        )

    def test_empty_and_none(self):
        empty = {"cookie": None, "publication": None, "user_id": None}
        self.assertEqual(self.parse(None), empty)
        self.assertEqual(self.parse("   "), empty)

    def test_bom_prefixed_json(self):
        bundle = {
            "publication": "demo",
            "user_id": "1",
            "cookie": "sid=1",
        }
        raw = "\ufeff" + json.dumps(bundle)
        self.assertEqual(self.parse(raw), bundle)

    def test_normalize_publication(self):
        self.assertEqual(self.normalize("https://demo.substack.com/p/hi"), "demo")
        self.assertEqual(self.normalize("demo.substack.com"), "demo")
        self.assertIsNone(self.normalize("open.substack.com"))
        self.assertIsNone(self.normalize("substack.com"))
        self.assertIsNone(self.normalize(""))


class LoadConfigFromBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmpdir.name, "config.json")
        self.cookie_path = os.path.join(self.tmpdir.name, "cookie.txt")
        self.ns = load_session_helpers(self.config_path, self.cookie_path)
        self.ns["run_setup_wizard"] = lambda prefill=None: (_ for _ in ()).throw(
            AssertionError("wizard should not run")
        )
        self.ns["fetch_identity_from_cookie"] = lambda cookie: (_ for _ in ()).throw(
            AssertionError("identity lookup should not run")
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_existing_config_wins(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"publication": "saved-pub", "user_id": "111"}, f)
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump({
                "publication": "ignored",
                "user_id": "222",
                "cookie": "sid=1",
            }, f)
        self.assertEqual(self.ns["load_config"](), ("saved-pub", "111"))
        self.assertEqual(self.ns["get_cookie"](), "sid=1")

    def test_bundle_creates_config_and_skips_wizard(self):
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump({
                "publication": "from-ext",
                "user_id": "987",
                "cookie": "substack.sid=fresh",
            }, f)
        self.assertEqual(self.ns["load_config"](), ("from-ext", "987"))
        with open(self.config_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved, {"publication": "from-ext", "user_id": "987"})
        self.assertEqual(self.ns["get_cookie"](), "substack.sid=fresh")

    def test_empty_cookie_file_is_ignored(self):
        open(self.cookie_path, "w", encoding="utf-8").close()
        self.assertIsNone(self.ns["get_cookie"]())

    def test_raw_cookie_looks_up_identity(self):
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            f.write("substack.sid=abc123; other=xyz")
        self.ns["fetch_identity_from_cookie"] = lambda cookie: ("looked-up", "777")
        self.assertEqual(self.ns["load_config"](), ("looked-up", "777"))
        with open(self.config_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved, {"publication": "looked-up", "user_id": "777"})
        self.assertEqual(self.ns["get_cookie"](), "substack.sid=abc123; other=xyz")

    def test_json_with_null_identity_looks_up(self):
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump({
                "publication": None,
                "user_id": None,
                "cookie": "sid=fresh",
            }, f)
        self.ns["fetch_identity_from_cookie"] = lambda cookie: ("from-api", "42")
        self.assertEqual(self.ns["load_config"](), ("from-api", "42"))

    def test_utf16_notepad_json_file(self):
        bundle = {
            "publication": "utf16-pub",
            "user_id": "321",
            "cookie": "sid=utf16",
        }
        with open(self.cookie_path, "w", encoding="utf-16") as f:
            f.write(json.dumps(bundle))
        self.assertEqual(self.ns["load_config"](), ("utf16-pub", "321"))
        self.assertEqual(self.ns["get_cookie"](), "sid=utf16")

    def test_env_var_json_bundle(self):
        old = os.environ.get("SUBSTACK_COOKIE")
        os.environ["SUBSTACK_COOKIE"] = json.dumps({
            "publication": "env-pub",
            "user_id": "555",
            "cookie": "env=cookie",
        })
        try:
            self.assertEqual(self.ns["load_config"](), ("env-pub", "555"))
            self.assertEqual(self.ns["get_cookie"](), "env=cookie")
        finally:
            if old is None:
                os.environ.pop("SUBSTACK_COOKIE", None)
            else:
                os.environ["SUBSTACK_COOKIE"] = old


class PickPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_session_helpers("unused-config.json", "unused-cookie.txt")
        cls.pick = staticmethod(cls.ns["pick_publication_from_profile"])

    def test_prefers_primary(self):
        data = {
            "publicationUsers": [
                {"publication": {"subdomain": "second"}, "role": "admin", "is_primary": False},
                {"publication": {"subdomain": "primary"}, "role": "admin", "is_primary": True},
            ]
        }
        self.assertEqual(self.pick(data), "primary")

    def test_prefers_admin_when_no_primary(self):
        data = {
            "publicationUsers": [
                {"publication": {"subdomain": "reader"}, "role": "subscriber", "is_primary": False},
                {"publication": {"subdomain": "mine"}, "role": "admin", "is_primary": False},
            ]
        }
        self.assertEqual(self.pick(data), "mine")

    def test_empty(self):
        self.assertIsNone(self.pick({}))
        self.assertIsNone(self.pick({"publicationUsers": []}))


if __name__ == "__main__":
    unittest.main()
