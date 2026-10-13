"""Types commands into the Claude Code tmux pane."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def tmux(*args):
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


WINDOWS = os.name == "nt" and not shutil.which("tmux")  # no tmux on Windows: target is a claude.exe pid


def detect_win():
    """PID of the newest interactive claude.exe (skips SDK/--print and browser-host instances)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
          "Where-Object { $_.CommandLine -notmatch '--output-format|--chrome-native-host| -p ' } | "
          "Sort-Object CreationDate | Select-Object -Last 1 -ExpandProperty ProcessId")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return r.stdout.strip() or None


watcher = None  # the one helper left behind to answer the "Switch model?" dialog; a new send replaces it


def send_win(pid, text, confirm):
    global watcher
    helper = Path(__file__).with_name("wininject.py")
    args = [sys.executable, str(helper), str(pid), text] + (["--confirm"] if confirm else [])
    for attempt in range(3):  # AttachConsole occasionally fails with "Access is denied"; a moment later it works
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=0x00000008)  # DETACHED_PROCESS: helper has no console, so it can attach to claude's
        if p.stdout.readline().strip() == "typed":
            if watcher and watcher.poll() is None:
                watcher.kill()  # two watchers would both answer the dialog, and the second "1" lands in Claude's prompt
            watcher = p if confirm else None
            return 0, ""
        code, err = p.wait() or 1, p.stderr.read().strip()
        if "denied" not in err:
            break
        time.sleep(0.2)
    return code, err


def detect():
    """Pane id of the first pane running claude, other than this one."""
    if WINDOWS:
        return detect_win()
    if not shutil.which("tmux"):
        return None
    code, out = tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}")
    me = os.environ.get("TMUX_PANE")
    for line in out.splitlines() if code == 0 else []:
        pane, _, cmd = line.partition(" ")
        if cmd == "claude" and pane != me:
            return pane
    return None


class Bridge:
    def __init__(self, target=None, last=None):
        self.target = target or detect()
        self.pending = None  # one slot, the latest shift wins
        self.last = last  # last command actually sent

    def queue(self, cmd):
        self.pending = cmd

    def flush(self, wait):
        """Send the pending command unless wait is set. Return (status, cmd), or None if nothing to do."""
        cmd = self.pending
        if not cmd:
            return None
        if wait:
            return "waiting for idle", cmd
        self.pending = None
        if cmd == self.last and cmd.startswith("/model "):
            return "already live", cmd  # rapid A -> B -> A while busy: nothing to send
        err = self.send(cmd)
        if err:
            return err, cmd
        self.last = cmd
        return "sent", cmd

    def send(self, text):
        """Return an error message, or None on success."""
        if not WINDOWS and not shutil.which("tmux"):
            return "dry run, no tmux"
        self.target = self.target or detect()
        if not self.target:
            return "no claude session found, use --target"
        # Mid-conversation, /model opens a "Switch model?" dialog with "Yes" selected; one more Enter accepts it.
        # With no dialog, that Enter lands on an empty prompt and does nothing.
        confirm = text.startswith("/model ")
        for retry in (False, True):
            if WINDOWS:
                code, err = send_win(self.target, text, confirm)
            else:
                code, err = tmux("send-keys", "-t", self.target, "-l", text)  # -l: literal text, no key names
                if code == 0:
                    code, err = tmux("send-keys", "-t", self.target, "Enter")  # separate call = real key press
                if code == 0 and confirm:
                    time.sleep(0.8)
                    code, err = tmux("send-keys", "-t", self.target, "Enter")
            if code == 0:
                return None
            new = detect()  # pane gone, e.g. tmux restarted: try the pane running claude now
            if retry or not new or new == self.target:
                return err if WINDOWS else f"tmux: {err}"
            self.target = new
