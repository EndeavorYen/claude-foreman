"""Checks for scripts/statusline.py and scripts/remind.py. Run: python -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {**os.environ, "FOREMAN_STATE_DIR": str(self.dir / "state")}
        self.transcript = self.dir / "t.jsonl"
        self.transcript.write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, payload, **env):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / name)], input=json.dumps(payload),
                           capture_output=True, text=True, encoding="utf-8", env={**self.env, **env})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def status(self, tokens, sid="s1"):
        return self.run_script("statusline.py", {"session_id": sid, "model": {"display_name": "Fable 5.2"},
                               "context_window": {"context_window_size": 1_000_000, "used_percentage": tokens / 10_000,
                                                  "current_usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 10}}})

    def prompt(self, sid="s1", **env):
        out = self.run_script("remind.py", {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                                            "transcript_path": str(self.transcript), "cwd": str(self.dir)}, **env)
        return json.loads(out).get("systemMessage", "") if out else ""

    def set_last_stop(self, minutes_ago, sid="s1"):
        f = self.dir / "state" / f"{sid}.json"
        st = json.loads(f.read_text(encoding="utf-8"))
        st["lastStop"] = time.time() - minutes_ago * 60
        f.write_text(json.dumps(st), encoding="utf-8")

    def test_statusline_prints_size_and_survives_garbage(self):
        self.assertEqual(self.status(312_000), "[Fable 5.2] ctx 312k (31%)")
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "statusline.py")], input="not json",
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0)

    def test_quiet_when_small_or_recent(self):
        self.status(50_000)
        self.set_last_stop(600)
        self.assertEqual(self.prompt(), "")          # idle but small
        self.status(300_000)
        self.set_last_stop(5)
        self.assertEqual(self.prompt(), "")          # large but warm

    def test_idle_and_large_reminds_once_per_pause(self):
        self.status(300_000)
        self.set_last_stop(16 * 60)
        self.assertIn("閒置了 16.0 小時", self.prompt())
        self.assertEqual(self.prompt(), "")          # same pause: not again

    def test_big_mark_reminds_once(self):
        self.status(520_000)
        self.set_last_stop(1)
        self.assertIn("context 已經 520k", self.prompt())
        self.assertEqual(self.prompt(), "")

    def test_stop_records_time_and_switch_silences(self):
        self.status(300_000)
        self.run_script("remind.py", {"hook_event_name": "Stop", "session_id": "s1"})
        st = json.loads((self.dir / "state" / "s1.json").read_text(encoding="utf-8"))
        self.assertLess(time.time() - st["lastStop"], 5)
        self.set_last_stop(600)
        self.assertEqual(self.prompt(FOREMAN_REMIND="0"), "")

    def test_falls_back_to_transcript_usage_without_statusline(self):
        self.transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 5, "cache_read_input_tokens": 600_000}}}) + "\n", encoding="utf-8")
        self.assertIn("context 已經 600k", self.prompt(sid="s2"))

    def test_session_start_points_at_fresh_handoff_only(self):
        payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.dir), "session_id": "s3"}
        self.assertEqual(self.run_script("remind.py", payload), "")
        (self.dir / ".claude").mkdir()
        (self.dir / ".claude" / "handoff.md").write_text("x", encoding="utf-8")
        out = json.loads(self.run_script("remind.py", payload))
        self.assertIn(".claude/handoff.md", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.run_script("remind.py", {**payload, "source": "resume"}), "")


if __name__ == "__main__":
    unittest.main()
