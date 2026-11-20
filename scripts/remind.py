#!/usr/bin/env python3
"""Hook for UserPromptSubmit, Stop and SessionStart: tell the user when a fresh session would be cheaper.

Decides in code, speaks only when one of two things is true, and says each thing once per session:
  - the session sat idle long enough for the prompt cache to expire while the context is large
    (the next turn re-reads all of it at close to full price, so a fresh session loses nothing);
  - the context passed the big mark.
On SessionStart it points Claude at a handoff file if one is waiting.

Always exits 0: a reminder must never block a prompt.
Tunables (environment): FOREMAN_IDLE_MIN=60  FOREMAN_IDLE_TOKENS=100000  FOREMAN_BIG_TOKENS=500000  FOREMAN_REMIND=0 to silence.
"""
import json
import os
import sys
import time
from pathlib import Path

HANDOFF = Path(".claude") / "handoff.md"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def state_dir() -> Path:
    return Path(os.environ.get("FOREMAN_STATE_DIR") or Path.home() / ".claude" / "foreman-state")


def tokens_from_transcript(path: str):
    """Fallback when the status line is not installed: the last usage block in the transcript."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 400_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("isSidechain"):
                continue
            u = (e.get("message") or {}).get("usage") if isinstance(e.get("message"), dict) else None
            if u:
                return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    except Exception:
        pass
    return None


def session_start(data: dict) -> dict:
    f = Path(data.get("cwd") or ".") / HANDOFF
    if data.get("source") in ("startup", "clear") and f.is_file():
        age_h = (time.time() - f.stat().st_mtime) / 3600
        if age_h < 24 * 7:
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
                    f"上一個 session 留了交接檔 {HANDOFF.as_posix()}（{age_h:.0f} 小時前）。"
                    "使用者的第一句話如果是要接續先前的工作，先讀它；如果是不相干的新任務，不用讀。"}}
    return {}


def prompt_submit(data: dict) -> dict:
    sid = data.get("session_id") or "unknown"
    sf = state_dir() / f"{sid}.json"
    try:
        st = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
    except Exception:
        st = {}
    tokens = st.get("tokens") or tokens_from_transcript(data.get("transcript_path") or "")
    if not tokens:
        return {}
    # idle = time since Claude last finished a reply (recorded by the Stop hook); that is what the cache cares about.
    # The transcript's mtime is only a fallback: the prompt being submitted may already have touched it.
    idle_min = None
    try:
        last = st.get("lastStop") or os.path.getmtime(data["transcript_path"])
        idle_min = (time.time() - last) / 60
    except Exception:
        pass
    said = st.get("said") or {}
    msg = None
    big, idle_tok, idle_lim = env_int("FOREMAN_BIG_TOKENS", 500_000), env_int("FOREMAN_IDLE_TOKENS", 100_000), env_int("FOREMAN_IDLE_MIN", 60)
    k = f"{tokens / 1000:.0f}k"
    # the idle reminder may repeat after each long pause, but not twice for the same pause
    if idle_min is not None and idle_min >= idle_lim and tokens >= idle_tok and time.time() - said.get("idle", 0) > idle_lim * 60:
        msg = (f"foreman：這個 session 閒置了 {idle_min / 60:.1f} 小時，context {k}。快取已過期，這一輪會重讀全部。"
               "如果接下來是新的段落，先說「交接」讓 Claude 寫交接檔，再開新 session 會便宜很多。")
        said["idle"] = time.time()
    elif tokens >= big and not said.get("big"):
        msg = f"foreman：context 已經 {k}。找個段落點說「交接」，開新 session 接續。"
        said["big"] = True
    if not msg:
        return {}
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        st["said"] = said
        st.setdefault("tokens", tokens)
        sf.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass
    return {"systemMessage": msg}


def stop(data: dict) -> dict:
    sid = data.get("session_id")
    if sid:
        sf = state_dir() / f"{sid}.json"
        st = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
        st["lastStop"] = time.time()
        state_dir().mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(st), encoding="utf-8")
    return {}


def main() -> None:
    if os.environ.get("FOREMAN_REMIND") == "0":
        return
    try:
        data = json.load(sys.stdin)
        event = data.get("hook_event_name")
        out = session_start(data) if event == "SessionStart" else stop(data) if event == "Stop" else prompt_submit(data)
        if out:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
    sys.exit(0)
