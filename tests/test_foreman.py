"""Checks for skills/foreman/scripts/foreman.py. Run: python -m unittest discover tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "foreman" / "scripts" / "foreman.py"
OK = 'python -c "import sys; sys.exit(0)"'
BAD = 'python -c "import sys; sys.exit(1)"'.replace("python", f'"{sys.executable}"')
OK = OK.replace("python", f'"{sys.executable}"')


def report(unit="U1", status="PASS", files=("src/a.ts",), criteria=None):
    return json.dumps({
        "unit": unit, "model": "claude-sonnet-5-5", "status": status, "filesChanged": list(files),
        "criteria": criteria or [{"id": "C1", "status": "PASS", "evidence": "npm test: 12 passed",
                                  "run": True, "cmd": "npm test", "exit": 0}],
        "notDone": [], "unsure": [],
    })


class ForemanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"],
                    ["git", "commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(cmd, cwd=self.repo, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=None):
        p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
                           input=stdin, capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout + p.stderr

    def start(self, verify="gate"):
        self.assertEqual(self.run_cli("init", "--task", "t", "--mode", "delegate", "--reason", "2 units")[0], 0)
        self.assertEqual(self.run_cli("plan", "add", "U1", "--objective", "o", "--model", "sonnet",
                                      "--verify", verify, "--files", "src")[0], 0)

    def test_init_excludes_archive_and_refuses_second_run(self):
        self.start()
        self.assertIn(".claude/foreman-runs/", (self.repo / ".git" / "info" / "exclude").read_text())
        code, _ = self.run_cli("init", "--task", "t2", "--mode", "solo", "--reason", "r")
        self.assertEqual(code, 2)

    def test_plan_show_is_a_table(self):
        self.start()
        code, out = self.run_cli("plan", "show")
        self.assertEqual(code, 0)
        self.assertIn("| U1 | o | sonnet |", out)

    def test_pass_needs_report_then_own_gate(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "PASS")[0], 2)
        self.assertEqual(self.run_cli("report", "U1", "-", stdin=report())[0], 0)
        self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "PASS")[0], 2)
        self.assertEqual(self.run_cli("gate", "U1", "--cmd", OK)[0], 0)
        self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "PASS", "--tokens", "42000")[0], 0)
        self.assertEqual(self.run_cli("unit", "set", "U1", "integrated")[0], 0)

    def test_gate_before_report_does_not_count(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        self.run_cli("gate", "U1", "--cmd", OK)
        self.run_cli("report", "U1", "-", stdin=report())
        self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "PASS")[0], 2)

    def test_report_rejects_pass_without_evidence_or_run(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        no_ev = report(criteria=[{"id": "C1", "status": "PASS", "evidence": ""}])
        self.assertEqual(self.run_cli("report", "U1", "-", stdin=no_ev)[0], 3)
        not_run = report(criteria=[{"id": "C1", "status": "PASS", "evidence": "tests written", "run": True}])
        code, out = self.run_cli("report", "U1", "-", stdin=not_run)
        self.assertEqual(code, 3)
        self.assertIn("written is not run", out)

    def test_report_rejects_files_outside_scope_and_reads_fenced_block(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        self.assertEqual(self.run_cli("report", "U1", "-", stdin=report(files=("package.json",)))[0], 3)
        fenced = "done.\n```json\n" + report() + "\n```\n"
        self.assertEqual(self.run_cli("report", "U1", "-", stdin=fenced)[0], 0)

    def test_fourth_worker_dispatch_is_refused(self):
        self.start()
        for _ in range(3):
            self.assertEqual(self.run_cli("dispatch", "open", "U1")[0], 0)
            self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "FAIL", "--fail-kind", "spec")[0], 0)
        self.assertEqual(self.run_cli("dispatch", "open", "U1")[0], 2)

    def test_fail_needs_a_kind_and_failed_gate_exits_3(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        self.assertEqual(self.run_cli("dispatch", "close", "U1", "--result", "FAIL")[0], 1)
        self.assertEqual(self.run_cli("gate", "U1", "--cmd", BAD)[0], 3)

    def test_dependency_and_verifier_are_enforced(self):
        self.start(verify="gate+verifier")
        self.run_cli("plan", "add", "U2", "--objective", "o2", "--model", "haiku", "--verify", "gate", "--depends", "U1")
        self.assertEqual(self.run_cli("dispatch", "open", "U2")[0], 2)
        self.run_cli("dispatch", "open", "U1")
        self.run_cli("report", "U1", "-", stdin=report())
        self.run_cli("gate", "U1", "--cmd", OK)
        self.run_cli("dispatch", "close", "U1", "--result", "PASS")
        self.assertEqual(self.run_cli("unit", "set", "U1", "integrated")[0], 2)
        self.run_cli("dispatch", "open", "U1", "--role", "verifier", "--model", "haiku")
        self.run_cli("dispatch", "close", "U1", "--result", "PASS")
        self.assertEqual(self.run_cli("unit", "set", "U1", "integrated")[0], 0)
        self.assertEqual(self.run_cli("dispatch", "open", "U2")[0], 0)

    def test_finish_needs_ship_gate_then_logs_history_and_feedback(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        self.run_cli("report", "U1", "-", stdin=report())
        self.run_cli("gate", "U1", "--cmd", OK)
        self.run_cli("dispatch", "close", "U1", "--result", "PASS", "--tokens", "30000", "--duration", "120")
        self.assertEqual(self.run_cli("finish")[0], 2)
        self.run_cli("unit", "set", "U1", "integrated")
        self.assertEqual(self.run_cli("finish")[0], 2)
        self.run_cli("gate", "ship", "--cmd", OK)
        code, out = self.run_cli("finish")
        self.assertEqual(code, 0)
        self.assertIn("claude-sonnet-5-5 ×1（30k tok", out)
        hist = self.repo / ".claude" / "foreman-runs" / "history.jsonl"
        run_id = json.loads(hist.read_text(encoding="utf-8").splitlines()[0])["runId"]
        self.assertEqual(self.run_cli("feedback", run_id, "--issues", "1")[0], 0)
        code, out = self.run_cli("review")
        self.assertEqual(code, 0)
        self.assertIn("事後發現問題合計 1", out)

    def test_model_mismatch_warns_and_missing_model_fails(self):
        self.start()
        self.run_cli("dispatch", "open", "U1")
        code, out = self.run_cli("report", "U1", "-", stdin=report().replace("claude-sonnet-5-5", "claude-opus-5-5"))
        self.assertEqual(code, 0)
        self.assertIn("asked for sonnet", out)
        no_model = json.loads(report())
        del no_model["model"]
        self.assertEqual(self.run_cli("report", "U1", "-", stdin=json.dumps(no_model))[0], 3)

    def test_solo_run_has_no_plan_and_finishes(self):
        self.run_cli("init", "--task", "t", "--mode", "solo", "--reason", "one unit, needs a design decision")
        self.assertEqual(self.run_cli("plan", "add", "U1", "--objective", "o", "--model", "sonnet", "--verify", "gate")[0], 2)
        code, out = self.run_cli("finish")
        self.assertEqual(code, 0)
        self.assertIn("自己做", out)


if __name__ == "__main__":
    unittest.main()
