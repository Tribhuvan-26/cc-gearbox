"""config.json, state.json and the busy flag, all under ~/.config/gearbox."""
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("GEARBOX_HOME") or Path.home() / ".config" / "gearbox")
CONFIG, STATE, BUSY = HOME / "config.json", HOME / "state.json", HOME / "busy"


def _model(i, name):
    return {"type": "model", "id": i, "name": name}


DEFAULT = {
    "target": None,  # None = auto-detect the pane running claude
    "format": "slash",
    "sendWhen": "idle",
    "sound": True,
    "reducedMotion": False,
    "gears": {
        "1": _model("claude-haiku-5-5", "Haiku 5.5"),
        "2": _model("claude-sonnet-5-5", "Sonnet 5.5"),
        "3": _model("claude-opus-5-5", "Opus 5.5"),
        "4": _model("claude-fable-5-1", "Fable 5.1"),
    },
    "reverse": {"type": "previous"},
}


def validate(cfg):
    """Return an error message, or None if cfg is usable."""
    if not isinstance(cfg, dict):
        return "config must be a JSON object"
    if cfg.get("format", "slash") not in ("slash", "tmux"):
        return "format must be slash or tmux"
    if cfg.get("sendWhen", "idle") not in ("idle", "now"):
        return "sendWhen must be idle or now"
    if cfg.get("reverse", {"type": "previous"}) != {"type": "previous"}:
        return "reverse supports only {\"type\": \"previous\"}"
    gears = cfg.get("gears", {})
    if not isinstance(gears, dict):
        return "gears must be an object"
    for k, g in gears.items():
        t = g.get("type") if isinstance(g, dict) else None
        if k in ("5", "6"):
            continue  # older configs; those gears are gone
        if k not in {"1", "2", "3", "4"}:
            return f"unknown gear {k!r}"
        if t == "model" and not g.get("id"):
            return f"gear {k}: missing id"
        if t == "command" and not g.get("command"):
            return f"gear {k}: missing command"
        if t not in ("model", "command", "none"):
            return f"gear {k}: type must be model, command or none"
    return None


def load_config():
    """Return (config, error). A missing file is created with defaults."""
    if not CONFIG.exists():
        write_json(CONFIG, DEFAULT)
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"config.json: {e}"
    err = validate(cfg)
    return (None, f"config.json: {err}") if err else ({**DEFAULT, **cfg}, None)


def write_json(path, data):
    """Atomic: write a temp file, then rename, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_state(gear, shifter, busy):
    cur = shifter.current
    write_json(STATE, {
        "gear": gear,
        "model": cur,
        "modelName": shifter.name(cur) if cur else None,
        "previous": shifter.previous,
        "busy": busy,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def log(msg):
    """One line per shift and send result, so a lost shift can be traced afterwards."""
    with open(HOME / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  {msg}\n")


def is_busy():
    """Claude Code hooks create the flag on UserPromptSubmit and delete it on Stop."""
    try:
        return time.time() - BUSY.stat().st_mtime < 600  # an interrupted turn can skip Stop; a flag older than 10 min is stale
    except OSError:
        return False
