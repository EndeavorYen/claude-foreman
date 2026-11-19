#!/usr/bin/env python3
"""foreman: the ledger and the refusals behind the claude-foreman skill.

Prose rules get summarised away; this script refuses instead. It keeps one run
under <repo>/.claude/foreman-runs/<run>/run.json (git-excluded) and appends a
summary line to <repo>/.claude/foreman-runs/history.jsonl when the run ends.

Python 3.9+ standard library only, so it runs the same on Windows, macOS, Linux.

Exit codes: 0 ok, 1 usage or I/O error, 2 refused by policy, 3 gate or report FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MODELS = ("haiku", "sonnet", "opus", "fable")
ROLES = ("worker", "verifier")
MAX_WORKER_DISPATCHES = 3
REPORT_REQUIRED = ("unit", "model", "status", "filesChanged", "criteria", "notDone", "unsure")
CRITERION_ID = re.compile(r"^C\d+$")


# ---------- small helpers ----------

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def die(msg: str, code: int = 1) -> None:
    print(f"foreman: {msg}", file=sys.stderr)
    sys.exit(code)


def git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def repo_root(start: Path) -> Path:
    top = git("rev-parse", "--show-toplevel", cwd=start)
    if not top:
        die("not inside a git repository")
    return Path(top)


def runs_dir(root: Path) -> Path:
    return root / ".claude" / "foreman-runs"


def current_run(root: Path) -> Path:
    pointer = runs_dir(root) / "CURRENT"
    if not pointer.is_file():
        die("no open run: start one with `foreman.py init --task ...`")
    run = runs_dir(root) / pointer.read_text(encoding="utf-8").strip()
    if not (run / "run.json").is_file():
        die(f"run.json missing in {run}")
    return run


def load(run: Path) -> dict:
    return json.loads((run / "run.json").read_text(encoding="utf-8"))


def save(run: Path, data: dict) -> None:
    tmp = run / "run.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, run / "run.json")


def unit_of(data: dict, uid: str) -> dict:
    for u in data["units"]:
        if u["id"] == uid:
            return u
    die(f"unknown unit {uid}; add it with `plan add`")
    return {}


def exclude_runs(root: Path) -> None:
    git_dir = git("rev-parse", "--git-dir", cwd=root)
    if not git_dir:
        return
    exclude = (root / git_dir / "info" / "exclude") if not os.path.isabs(git_dir) else Path(git_dir) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    line = ".claude/foreman-runs/"
    text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if line not in text.splitlines():
        exclude.write_text(text + ("" if text.endswith("\n") or not text else "\n") + line + "\n", encoding="utf-8")


# ---------- commands ----------

def cmd_init(a, root: Path) -> None:
    rd = runs_dir(root)
    pointer = rd / "CURRENT"
    if pointer.is_file() and not a.force:
        die(f"run {pointer.read_text(encoding='utf-8').strip()} is still open: `finish` it or pass --force", 2)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run = rd / run_id
    (run / "gates").mkdir(parents=True, exist_ok=True)
    (run / "reports").mkdir(exist_ok=True)
    exclude_runs(root)
    data = {
        "runId": run_id, "task": a.task, "mainModel": a.main_model, "mode": a.mode,
        "gateReason": a.reason, "baselineSha": git("rev-parse", "HEAD", cwd=root),
        "startedAt": now(), "units": [], "finished": None, "baseTokens": a.base_tokens,
    }
    save(run, data)
    pointer.write_text(run_id, encoding="utf-8")
    print(f"run {run_id} · mode {a.mode} · baseline {data['baselineSha'][:10] or '(none)'}")
    print(f"archive: {run}")


def cmd_plan_add(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    if data["mode"] != "delegate":
        die("this run is mode=solo: nothing to plan; re-init with --mode delegate", 2)
    if any(u["id"] == a.unit for u in data["units"]):
        die(f"unit {a.unit} already planned")
    for dep in a.depends or []:
        unit_of(data, dep)
    data["units"].append({
        "id": a.unit, "objective": a.objective, "model": a.model, "effort": a.effort,
        "verify": a.verify, "depends": a.depends or [], "files": a.files or [],
        "status": "pending", "dispatches": [], "gates": [], "report": None,
    })
    save(run, data)
    print(f"planned {a.unit} → {a.model}")


def table(data: dict) -> str:
    rows = ["| 單元 | 目標 | 模型 | effort | 驗證 | 依賴 | 狀態 | 派遣 |", "|---|---|---|---|---|---|---|---|"]
    for u in data["units"]:
        workers = sum(1 for d in u["dispatches"] if d["role"] == "worker")
        rows.append(f"| {u['id']} | {u['objective']} | {u['model']} | {u['effort']} | {u['verify']} | "
                    f"{','.join(u['depends']) or '—'} | {u['status']} | {workers}/{MAX_WORKER_DISPATCHES} |")
    return "\n".join(rows)


def cmd_plan_show(a, root: Path) -> None:
    data = load(current_run(root))
    print(f"**foreman 計畫** · {data['task']} · 主模型 {data['mainModel']}")
    print(f"判斷：{data['gateReason']}\n")
    print(table(data))


def cmd_dispatch_open(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    u = unit_of(data, a.unit)
    if u["status"] in ("integrated", "surfaced"):
        die(f"{a.unit} is {u['status']}: no more dispatches", 2)
    for dep in u["depends"]:
        if unit_of(data, dep)["status"] != "integrated":
            die(f"{a.unit} depends on {dep}, which is not integrated yet", 2)
    if a.role == "worker":
        n = sum(1 for d in u["dispatches"] if d["role"] == "worker")
        if n >= MAX_WORKER_DISPATCHES:
            die(f"{a.unit} used {n}/{MAX_WORKER_DISPATCHES} worker dispatches: surface it, do not retry", 2)
    if any(d["result"] == "open" for d in u["dispatches"]):
        die(f"{a.unit} has an open dispatch: close it first", 2)
    u["dispatches"].append({"n": len(u["dispatches"]) + 1, "role": a.role, "model": a.model or u["model"],
                            "openedAt": now(), "result": "open", "tokens": None, "durationSec": None,
                            "failKind": None})
    u["status"] = "in-flight"
    save(run, data)
    print(f"{a.unit} dispatch #{len(u['dispatches'])} open ({a.role}, {a.model or u['model']})")


def cmd_dispatch_close(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    u = unit_of(data, a.unit)
    open_d = [d for d in u["dispatches"] if d["result"] == "open"]
    if not open_d:
        die(f"{a.unit} has no open dispatch")
    d = open_d[-1]
    if a.result == "PASS" and d["role"] == "worker":
        if not u["report"] or u["report"].get("verdict") != "PASS":
            die(f"{a.unit}: a worker PASS needs a checked report (`report {a.unit} <file>`) first", 2)
        if not any(g["exit"] == 0 and g.get("afterReport") for g in u["gates"]):
            die(f"{a.unit}: a worker PASS needs a gate you ran yourself after the report (`gate {a.unit} ...`)", 2)
    if a.result == "FAIL" and not a.fail_kind:
        die("a FAIL needs --fail-kind spec|environment|capability|unverifiable", 1)
    d.update(result=a.result, tokens=a.tokens, durationSec=a.duration, closedAt=now(), failKind=a.fail_kind)
    if a.model_reported:
        note_model(d, a.model_reported)
    if not d.get("modelReported"):
        print(f"note: {a.unit} dispatch #{d['n']} has no reported model (pass --model-reported)", file=sys.stderr)
    u["status"] = "passed" if a.result == "PASS" else "pending"
    if a.result == "FAIL" and a.fail_kind == "unverifiable":
        u["status"] = "surfaced"
    save(run, data)
    print(f"{a.unit} dispatch #{d['n']} {a.result}" + (f" ({a.fail_kind})" if a.fail_kind else ""))


def note_model(d: dict, reported: str) -> None:
    """Record the model the subagent says it ran on; shout when it is not the one that was asked for."""
    d["modelReported"] = reported
    if d["model"] not in reported.lower():
        print(f"WARNING: asked for {d['model']} but the subagent reports `{reported}`: routing is being overridden "
              f"(check CLAUDE_CODE_SUBAGENT_MODEL and the agent definition's model)", file=sys.stderr)


def check_report(rep: dict, unit: dict) -> list[str]:
    errs = []
    for k in REPORT_REQUIRED:
        if k not in rep:
            errs.append(f"missing key `{k}`")
    if errs:
        return errs
    if rep["unit"] != unit["id"]:
        errs.append(f"report is for {rep['unit']}, not {unit['id']}")
    if rep["status"] == "ASK":
        # the worker stopped to ask: answer it and resume the same agent; nothing else is checked yet
        if not rep.get("questions"):
            errs.append("status ASK needs a non-empty `questions` list")
        return errs
    if rep["status"] not in ("PASS", "FAIL"):
        errs.append("status must be PASS, FAIL or ASK")
    if not isinstance(rep["criteria"], list) or not rep["criteria"]:
        errs.append("criteria must be a non-empty list")
        return errs
    allowed = [str(f).replace("\\", "/") for f in unit.get("files") or []]
    for f in rep["filesChanged"]:
        f = str(f).replace("\\", "/")
        if allowed and not any(f == p or f.startswith(p.rstrip("/") + "/") for p in allowed):
            errs.append(f"changed `{f}`, outside the unit's files {allowed}")
    for c in rep["criteria"]:
        cid = c.get("id", "?")
        if not CRITERION_ID.match(str(cid)):
            errs.append(f"criterion id `{cid}` is not C<n>")
        st = c.get("status")
        if st not in ("PASS", "FAIL", "PENDING"):
            errs.append(f"{cid}: status must be PASS, FAIL or PENDING")
        if st == "PASS":
            if not str(c.get("evidence", "")).strip():
                errs.append(f"{cid}: PASS without evidence")
            if c.get("run"):
                if not str(c.get("cmd", "")).strip() or c.get("exit") != 0:
                    errs.append(f"{cid}: a run criterion PASS needs the command it ran and exit 0 (written is not run)")
    if rep["status"] == "PASS" and any(c.get("status") != "PASS" for c in rep["criteria"]):
        errs.append("status PASS while a criterion is not PASS")
    return errs


def cmd_report(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    u = unit_of(data, a.unit)
    raw = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    text = m.group(1) if m else raw.strip()
    try:
        rep = json.loads(text)
    except json.JSONDecodeError as e:
        die(f"report is not one JSON object: {e}", 3)
    errs = check_report(rep, u)
    n = len(u["dispatches"])
    (run / "reports" / f"{a.unit}-{n}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    verdict = "PASS" if not errs and rep["status"] == "PASS" else "FAIL"
    if not errs and rep["status"] == "ASK":
        u["dispatches"][-1].setdefault("questions", []).append(rep["questions"])
        save(run, data)
        print(f"{a.unit} ASK: the worker needs an answer before it can go on:")
        for q in rep["questions"]:
            print(f"  ? {q}")
        print("answer from what the user decided and what the repo says, then resume the SAME agent "
              "(SendMessage); if you cannot answer it yourself, ask the user. The dispatch stays open.")
        return
    u["report"] = {"dispatch": n, "verdict": verdict, "errors": errs, "notDone": rep.get("notDone"),
                   "unsure": rep.get("unsure")}
    for g in u["gates"]:
        g["afterReport"] = False
    if u["dispatches"] and isinstance(rep, dict) and rep.get("model"):
        note_model(u["dispatches"][-1], str(rep["model"]))
    save(run, data)
    if errs:
        print(f"{a.unit} report FAIL:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(3)
    print(f"{a.unit} report {verdict}" + ("" if verdict == "PASS" else " (the worker reported FAIL)"))
    if rep.get("unsure"):
        print(f"  unsure: {rep['unsure']}")
    if verdict != "PASS":
        sys.exit(3)


def cmd_gate(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    u = unit_of(data, a.unit) if a.unit != "ship" else None
    cwd = Path(a.cwd).resolve() if a.cwd else root
    worst = 0
    for i, cmd in enumerate(a.cmd, 1):
        t0 = time.time()
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        dur = round(time.time() - t0, 1)
        log = run / "gates" / f"{a.unit}-{len(u['gates']) + i if u else i}-{int(t0)}.log"
        log.write_text(f"$ {cmd}\n(cwd {cwd}, exit {p.returncode}, {dur}s)\n\n{p.stdout}\n{p.stderr}", encoding="utf-8")
        mark = "PASS" if p.returncode == 0 else "FAIL"
        print(f"{a.unit} gate {mark} exit {p.returncode} {dur}s · {cmd} · log {log.name}")
        if p.returncode != 0:
            tail = (p.stdout + p.stderr).strip().splitlines()[-15:]
            print("    " + "\n    ".join(tail))
        rec = {"cmd": cmd, "exit": p.returncode, "durationSec": dur, "log": log.name, "at": now(), "afterReport": True}
        if u is not None:
            u["gates"].append(rec)
        else:
            data.setdefault("shipGates", []).append(rec)
        worst = worst or p.returncode
    save(run, data)
    if worst:
        sys.exit(3)


def cmd_unit_set(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    u = unit_of(data, a.unit)
    if a.status == "integrated" and u["status"] != "passed":
        die(f"{a.unit} is {u['status']}: only a passed unit can be integrated", 2)
    if a.status == "integrated" and u["verify"] == "gate+verifier":
        last = u["dispatches"][-1] if u["dispatches"] else None
        if not last or last["role"] != "verifier" or last["result"] != "PASS":
            die(f"{a.unit} is planned gate+verifier: its last dispatch must be a verifier PASS", 2)
    u["status"] = a.status
    if a.note:
        u["note"] = a.note
    save(run, data)
    print(f"{a.unit} → {a.status}")


def summarise(data: dict) -> dict:
    per_model: dict[str, dict] = {}
    disp = retries = verifier_fails = 0
    for u in data["units"]:
        workers = [d for d in u["dispatches"] if d["role"] == "worker"]
        retries += max(0, len(workers) - 1)
        for d in u["dispatches"]:
            disp += 1
            m = per_model.setdefault(d.get("modelReported") or d["model"] + "(未回報)", {"dispatches": 0, "tokens": 0, "seconds": 0.0})
            m["dispatches"] += 1
            m["tokens"] += d["tokens"] or 0
            m["seconds"] += d["durationSec"] or 0
            if d["role"] == "verifier" and d["result"] == "FAIL":
                verifier_fails += 1
    gate_fails = sum(1 for u in data["units"] for g in u["gates"] if g["exit"] != 0)
    return {"dispatches": disp, "retries": retries, "verifierCaught": verifier_fails,
            "gateFails": gate_fails, "perModel": per_model,
            "units": {s: sum(1 for u in data["units"] if u["status"] == s)
                      for s in ("integrated", "passed", "surfaced", "pending", "in-flight")}}


def cost_line(data: dict) -> str:
    s = summarise(data)
    if data["mode"] == "solo":
        return f"foreman：自己做（{data['gateReason']}）"
    parts = [f"{m} ×{v['dispatches']}（{v['tokens'] / 1000:.0f}k tok, {v['seconds'] / 60:.0f} 分）"
             for m, v in sorted(s["perModel"].items())]
    total = sum(v["tokens"] for v in s["perModel"].values())
    base = data.get("baseTokens")
    overhead = f"（其中固定開銷約 {base * s['dispatches'] / 1000:.0f}k＝{base / 1000:.0f}k×{s['dispatches']} 次）" if base else ""
    return (f"foreman：{data['mainModel']} 規劃＋驗收｜{'、'.join(parts) or '無派遣'}｜子代理合計 {total / 1000:.0f}k tok{overhead}"
            f"｜重派 {s['retries']}｜關卡 1 擋下 {s['gateFails']}｜驗證者抓到 {s['verifierCaught']}"
            f"｜交付 {s['units']['integrated']}、擱置 {s['units']['surfaced']}")


def cmd_cost(a, root: Path) -> None:
    print(cost_line(load(current_run(root))))


def cmd_finish(a, root: Path) -> None:
    run = current_run(root)
    data = load(run)
    if data["mode"] == "delegate":
        open_units = [u["id"] for u in data["units"] if u["status"] in ("pending", "in-flight", "passed")]
        if open_units and not a.force:
            die(f"units not integrated or surfaced: {', '.join(open_units)} (pass --force to park them)", 2)
        if not data.get("shipGates") and not a.force:
            die("no ship gate recorded: run `gate ship --cmd ...` with the repo's own checks", 2)
    data["finished"] = now()
    save(run, data)
    hist = runs_dir(root) / "history.jsonl"
    entry = {"runId": data["runId"], "task": data["task"], "mode": data["mode"], "mainModel": data["mainModel"],
             "finished": data["finished"], **summarise(data), "issuesFoundLater": None}
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    (runs_dir(root) / "CURRENT").unlink(missing_ok=True)
    print(cost_line(data))
    print(f"logged to {hist}; afterwards record what the user found: `feedback {data['runId']} --issues <n>`")


def cmd_feedback(a, root: Path) -> None:
    hist = runs_dir(root) / "history.jsonl"
    if not hist.is_file():
        die("no history yet")
    lines = hist.read_text(encoding="utf-8").splitlines()
    hit = False
    for i, line in enumerate(lines):
        e = json.loads(line)
        if e["runId"] == a.run:
            e["issuesFoundLater"] = a.issues
            if a.note:
                e["feedbackNote"] = a.note
            lines[i] = json.dumps(e, ensure_ascii=False)
            hit = True
    if not hit:
        die(f"run {a.run} not in history")
    hist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{a.run}: issues found later = {a.issues}")


def cmd_review(a, root: Path) -> None:
    hist = runs_dir(root) / "history.jsonl"
    if not hist.is_file():
        die("no history yet")
    rows = [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()]
    print("| run | 任務 | 模式 | 派遣 | 重派 | 關卡擋下 | 驗證抓到 | 事後發現 |")
    print("|---|---|---|---|---|---|---|---|")
    for e in rows:
        later = "?" if e.get("issuesFoundLater") is None else e["issuesFoundLater"]
        print(f"| {e['runId']} | {e['task'][:30]} | {e['mode']} | {e['dispatches']} | {e['retries']} | "
              f"{e['gateFails']} | {e['verifierCaught']} | {later} |")
    d = [e for e in rows if e["mode"] == "delegate"]
    if d:
        known = [e for e in d if e.get("issuesFoundLater") is not None]
        print(f"\n派工 {len(d)} 次；有回填的 {len(known)} 次，事後發現問題合計 "
              f"{sum(e['issuesFoundLater'] for e in known)}；平均重派 {sum(e['retries'] for e in d) / len(d):.1f}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="foreman.py", description=__doc__.splitlines()[0])
    p.add_argument("--repo", help="repository path (default: the git repo of the cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="open a run")
    s.add_argument("--task", required=True)
    s.add_argument("--mode", choices=("delegate", "solo"), required=True)
    s.add_argument("--reason", required=True, help="one line: why the gate chose this mode")
    s.add_argument("--main-model", default="opus", choices=MODELS)
    s.add_argument("--base-tokens", type=int, help="tokens a do-nothing subagent costs here (from the probe)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("plan", help="plan units")
    ps = s.add_subparsers(dest="plan_cmd", required=True)
    pa = ps.add_parser("add")
    pa.add_argument("unit")
    pa.add_argument("--objective", required=True)
    pa.add_argument("--model", required=True, choices=MODELS)
    pa.add_argument("--effort", default="medium", choices=("low", "medium", "high", "xhigh", "max"))
    pa.add_argument("--verify", required=True, choices=("gate", "gate+verifier"))
    pa.add_argument("--depends", nargs="*")
    pa.add_argument("--files", nargs="*", help="paths the worker may change (prefixes allowed)")
    pa.set_defaults(fn=cmd_plan_add)
    pshow = ps.add_parser("show")
    pshow.set_defaults(fn=cmd_plan_show)

    s = sub.add_parser("dispatch", help="record a dispatch")
    ds = s.add_subparsers(dest="d_cmd", required=True)
    do = ds.add_parser("open")
    do.add_argument("unit")
    do.add_argument("--role", default="worker", choices=ROLES)
    do.add_argument("--model", choices=MODELS)
    do.set_defaults(fn=cmd_dispatch_open)
    dc = ds.add_parser("close")
    dc.add_argument("unit")
    dc.add_argument("--result", required=True, choices=("PASS", "FAIL"))
    dc.add_argument("--fail-kind", choices=("spec", "environment", "capability", "unverifiable"))
    dc.add_argument("--tokens", type=int)
    dc.add_argument("--duration", type=float, help="seconds")
    dc.add_argument("--model-reported", help="exact model ID the subagent says it ran on (verifiers; workers put it in the report)")
    dc.set_defaults(fn=cmd_dispatch_close)

    s = sub.add_parser("report", help="check a worker report (file path or - for stdin)")
    s.add_argument("unit")
    s.add_argument("file")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("gate", help="run checks yourself and record them (unit id, or ship)")
    s.add_argument("unit")
    s.add_argument("--cmd", action="append", required=True)
    s.add_argument("--cwd")
    s.set_defaults(fn=cmd_gate)

    s = sub.add_parser("unit", help="set a unit's status")
    us = s.add_subparsers(dest="u_cmd", required=True)
    uset = us.add_parser("set")
    uset.add_argument("unit")
    uset.add_argument("status", choices=("integrated", "surfaced", "pending"))
    uset.add_argument("--note")
    uset.set_defaults(fn=cmd_unit_set)

    s = sub.add_parser("cost", help="print the cost line")
    s.set_defaults(fn=cmd_cost)
    s = sub.add_parser("finish", help="close the run and log it to history")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_finish)
    s = sub.add_parser("feedback", help="record issues the user found after delivery")
    s.add_argument("run")
    s.add_argument("--issues", type=int, required=True)
    s.add_argument("--note")
    s.set_defaults(fn=cmd_feedback)
    s = sub.add_parser("review", help="table of past runs")
    s.set_defaults(fn=cmd_review)

    a = p.parse_args(argv)
    root = repo_root(Path(a.repo).resolve() if a.repo else Path.cwd())
    a.fn(a, root)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
