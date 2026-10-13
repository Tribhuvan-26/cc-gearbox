#!/usr/bin/env python3
"""Claude Code status line: prints the engaged gear, with a mark if Claude reports a different model."""
import json
import os
import sys
from pathlib import Path

home = Path(os.environ.get("GEARBOX_HOME") or Path.home() / ".config" / "gearbox")
try:
    s = json.loads((home / "state.json").read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("gearbox: not running")
    sys.exit()
try:
    live = json.load(sys.stdin).get("model") or {}  # Claude Code passes session info on stdin
except (ValueError, AttributeError):
    live = {}
out = f"gear {s.get('gear')} / {s.get('modelName') or '?'}"
if live.get("id") and s.get("model") and not live["id"].startswith(s["model"]):
    out += f"  ≠ {live.get('display_name') or live['id']}"  # someone typed /model by hand, or a send is still waiting
print(out)
