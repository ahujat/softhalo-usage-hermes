"""Unit tests for the Soft Halo Usage Hermes adapter. Run: python -m unittest discover tests"""

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location("softhalo_usage", Path(__file__).resolve().parents[1] / "__init__.py")
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)

NOW = datetime(2026, 11, 9, 10, 0, 0, tzinfo=timezone.utc)
USAGE = {"input_tokens": 12, "output_tokens": 40, "cache_read_tokens": 900, "cache_write_tokens": 30,
         "reasoning_tokens": 7, "request_count": 1, "prompt_tokens": 942, "total_tokens": 982}


def main_payload(**extra):
    payload = dict(session_id="s1", task_id="t1", turn_id="u1", api_request_id="req-1", provider="anthropic",
                   model="claude-sonnet-5-5", response_model="claude-sonnet-5-5-20261101", ended_at=NOW.timestamp(),
                   usage=USAGE, response={"content": "secret answer"}, request={"messages": ["secret prompt"]},
                   assistant_message={"content": "secret answer"}, telemetry_schema_version="hermes.observer.v1")
    payload.update(extra)
    return payload


class BuildEventTests(unittest.TestCase):
    def test_main_request_maps_onto_the_four_buckets(self):
        e = sh.build_event("post_api_request", main_payload(), "hm-x", NOW)
        self.assertEqual(e["usage"], {"input_uncached": 12, "cache_read": 900, "cache_write": 30, "output": 40, "reasoning": 7})
        self.assertEqual(e["format"], "softhalo.event/1")
        self.assertEqual(e["app"], "hermes")
        self.assertEqual(e["call_kind"], "main")
        self.assertEqual(e["status"], "completed")
        self.assertEqual(e["model"], "claude-sonnet-5-5-20261101")
        self.assertEqual(e["provider"], "anthropic")
        self.assertEqual(e["request_id"], "req-1")
        self.assertEqual(e["request_id_scope"], "session")
        self.assertEqual(e["completed_at"], "2026-11-09T10:00:00.000Z")
        self.assertRegex(e["day"], r"^\d{4}-\d{2}-\d{2}$")

    def test_no_prompt_response_or_message_is_copied(self):
        text = json.dumps(sh.build_event("post_api_request", main_payload(), "p", NOW))
        self.assertNotIn("secret", text)

    def test_auxiliary_calls_are_labelled_and_carry_no_request_id(self):
        e = sh.build_event("post_auxiliary_call", dict(session_id="s1", aux_task="title", api_request_id="x",
                                                        provider="openrouter", model="m", usage=USAGE), "p", NOW)
        self.assertEqual(e["call_kind"], "auxiliary")
        self.assertNotIn("request_id", e)

    def test_auxiliary_errors_and_streaming_calls_count_as_requests_without_usage(self):
        failed = sh.build_event("post_auxiliary_call", dict(session_id="s1", model="m", usage=None,
                                                            error={"type": "Timeout"}), "p", NOW)
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["usage"])
        streaming = sh.build_event("post_auxiliary_call", dict(session_id="s1", model="m", usage=None), "p", NOW)
        self.assertEqual(streaming["status"], "completed")
        self.assertIsNone(streaming["usage"])

    def test_missing_counters_are_null_never_zero(self):
        e = sh.build_event("post_api_request", main_payload(usage={"output_tokens": 5}), "p", NOW)
        self.assertEqual(e["usage"], {"input_uncached": None, "cache_read": None, "cache_write": None, "output": 5, "reasoning": None})
        self.assertIsNone(sh.build_event("post_api_request", main_payload(usage={}), "p", NOW)["usage"])

    def test_a_delegated_subagent_is_labelled(self):
        e = sh.build_event("post_api_request", main_payload(parent_session_id="parent"), "p", NOW)
        self.assertEqual(e["call_kind"], "subagent")
        self.assertEqual(e["parent_session_id"], "parent")

    def test_an_empty_session_id_still_gives_a_valid_record(self):
        e = sh.build_event("post_auxiliary_call", dict(session_id="", model="m", usage=USAGE), "p", NOW)
        self.assertEqual(e["session_id"], "no-session")


class IdentityTests(unittest.TestCase):
    def test_profile_is_a_one_way_hash_that_ignores_path_spelling(self):
        a = sh.profile_id("C:\\Users\\u\\.hermes\\")
        self.assertEqual(a, sh.profile_id("c:/users/u/.hermes"))
        self.assertNotEqual(a, sh.profile_id("c:/users/u/.hermes/profiles/work"))
        self.assertRegex(a, r"^hm-[0-9a-f]{20}$")

    def test_usage_folder_follows_each_system(self):
        self.assertEqual(sh.usage_root({"LOCALAPPDATA": "C:\\L"}, "win32", "C:\\U"), Path("C:\\L") / "Softhalo" / "usage")
        self.assertIsNone(sh.usage_root({}, "win32", "C:\\U"))
        self.assertEqual(sh.usage_root({}, "darwin", "/Users/u"), Path("/Users/u/Library/Application Support/Softhalo/usage"))
        self.assertEqual(sh.usage_root({"XDG_STATE_HOME": "/s"}, "linux", "/home/u"), Path("/s/softhalo/usage"))
        self.assertEqual(sh.usage_root({}, "linux", "/home/u"), Path("/home/u/.local/state/softhalo/usage"))

    def test_inside_wsl_the_soft_halo_folder_of_the_windows_user_is_used(self):
        self.assertTrue(sh.is_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, "linux", "6.6.0"))
        self.assertTrue(sh.is_wsl({}, "linux", "5.15.153.1-microsoft-standard-WSL2"))
        self.assertFalse(sh.is_wsl({}, "linux", "6.8.0-generic"))
        self.assertFalse(sh.is_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, "win32", ""))

        users = Path(tempfile.mkdtemp(prefix="softhalo-hm-users-"))
        try:
            wsl = {"WSL_DISTRO_NAME": "Ubuntu", "USER": "ann"}
            def resolve(env):
                return sh.resolve_root(env, "linux", "/home/ann", "", str(users))
            (users / "Public" / "AppData" / "Local" / "Softhalo").mkdir(parents=True)
            (users / "Other" / "AppData" / "Local" / "Temp").mkdir(parents=True)
            self.assertIsNone(resolve(wsl))
            (users / "Sam" / "AppData" / "Local" / "Softhalo").mkdir(parents=True)
            self.assertEqual(resolve(wsl), users / "Sam" / "AppData" / "Local" / "Softhalo" / "usage")
            (users / "Ann" / "AppData" / "Local" / "Softhalo").mkdir(parents=True)
            self.assertEqual(resolve(wsl), users / "Ann" / "AppData" / "Local" / "Softhalo" / "usage")
            self.assertIsNone(resolve(dict(wsl, USER="bob")))
            self.assertEqual(resolve(dict(wsl, SOFTHALO_USAGE_DIR="/mnt/d/x/")), Path("/mnt/d/x"))
        finally:
            shutil.rmtree(users, ignore_errors=True)

    def test_file_names_stay_plain(self):
        self.assertEqual(sh.safe_name("../../etc"), "______etc")
        self.assertEqual(sh.safe_name(""), "unknown")


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="softhalo-hm-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_publishes_one_whole_json_file_and_no_tmp(self):
        e = sh.build_event("post_api_request", main_payload(session_id="sess/1"), "p", NOW)
        path = sh.publish(self.root, e, NOW)
        files = sorted(p.name for p in (self.root / "inbox").iterdir())
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0], r"^hermes-sess_1-\d+-\d+-[0-9a-f]{8}\.json$")
        back = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(back["session_id"], "sess/1")
        self.assertNotIn("dropped_before", back)

    def test_two_events_in_the_same_millisecond_get_different_names(self):
        e = sh.build_event("post_api_request", main_payload(), "p", NOW)
        sh.publish(self.root, e, NOW)
        sh.publish(self.root, e, NOW)
        self.assertEqual(len(list((self.root / "inbox").iterdir())), 2)

    def test_while_inbox_is_full_nothing_is_written_and_next_event_reports_the_gap(self):
        (self.root / "inbox").mkdir()
        (self.root / "inbox" / ".full").write_text("")
        e = sh.build_event("post_api_request", main_payload(), "p", NOW)
        self.assertIsNone(sh.publish(self.root, e, NOW))
        self.assertIsNone(sh.publish(self.root, e, NOW))
        self.assertEqual([p.name for p in (self.root / "inbox").iterdir()], [".full"])

        (self.root / "inbox" / ".full").unlink()
        path = sh.publish(self.root, e, NOW)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["dropped_before"], 2)
        self.assertFalse((self.root / "hermes-dropped.json").exists())


class RegisterTests(unittest.TestCase):
    def test_registers_only_the_two_observer_hooks_and_a_hook_call_writes_a_file(self):
        root = Path(tempfile.mkdtemp(prefix="softhalo-hm-reg-"))
        try:
            hooks = {}

            class Ctx:
                def register_hook(self, name, fn):
                    hooks[name] = fn

            import os
            saved = dict(os.environ)
            # Point every route at the temporary folder. SOFTHALO_USAGE_DIR wins on any system, so the
            # test never reaches the real Soft Halo folder, not even inside WSL.
            os.environ["SOFTHALO_USAGE_DIR"] = str(root / "usage")
            os.environ["LOCALAPPDATA"] = str(root)
            os.environ["XDG_STATE_HOME"] = str(root)
            os.environ["HOME"] = str(root)
            try:
                sh.register(Ctx())
            finally:
                os.environ.clear()
                os.environ.update(saved)
            self.assertEqual(sorted(hooks), ["post_api_request", "post_auxiliary_call"])
            hooks["post_api_request"](**main_payload())
            written = list(root.rglob("inbox/hermes-*.json"))
            self.assertEqual(len(written), 1)
            # A hook never raises, even with a payload it cannot use.
            hooks["post_auxiliary_call"](usage=object(), ended_at="not a time")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
