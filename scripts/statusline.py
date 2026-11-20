#!/usr/bin/env python3
"""Status line for Claude Code: model and context size. Also leaves the size where the reminder hook can read it.

Claude Code pipes session JSON on stdin; whatever this prints is the status line. It must never fail loudly.
"""
import json
import os
import sys
import time
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("FOREMAN_STATE_DIR") or Path.home() / ".claude" / "foreman-state")


def context_tokens(cw: dict):
    cu = cw.get("current_usage") or {}
    n = sum(int(cu.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    if n:
        return n
    pct, size = cw.get("used_percentage"), cw.get("context_window_size")
    return int(pct * size / 100) if pct is not None and size else None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("")
        return
    cw = data.get("context_window") or {}
    tokens = context_tokens(cw)
    model = (data.get("model") or {}).get("display_name") or "?"
    if tokens is None:
        print(f"[{model}] ctx —")
        return
    pct = cw.get("used_percentage")
    print(f"[{model}] ctx {tokens / 1000:.0f}k" + (f" ({pct:.0f}%)" if pct is not None else ""))
    sid = data.get("session_id")
    if sid:
        try:
            d = state_dir()
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{sid}.json"
            old = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
            old.update(tokens=tokens, at=time.time())
            f.write_text(json.dumps(old), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
