"""Textual shifter: dial, gate, readout, command line, shift log."""
import argparse
import math
import time
from datetime import datetime

from rich.text import Text
from textual.app import App
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from . import bridge, gate, skin, store

W = 42  # drawing width; fits a 42-column pane
COL_X = [7, 18, 29]  # screen column of each gate column
ROW_Y = {-2: 1, -1: 2, 0: 3, 1: 4, 2: 5}  # screen row of each gate y; rows 0 and 6 hold gear numbers
STEP_S, SWING_S, BOUNCE_S, REST_S = 0.11, 0.45, 0.15, 0.7


def grid(h):
    return [[(" ", "") for _ in range(W)] for _ in range(h)]


def to_text(cells):
    t = Text()
    for i, row in enumerate(cells):
        for ch, st in row:
            t.append(ch, st or None)
        if i < len(cells) - 1:
            t.append("\n")
    return t


def draw_gate(knob, engaged, shifter, bounce):
    c = grid(11)
    side = gate.POS.get(engaged, (None, 0))
    for sx in range(COL_X[0], COL_X[-1] + 1):
        c[3][sx] = ("─", "dim")
    for x, sx in enumerate(COL_X):
        c[3][sx] = ("├┼┘"[x], "dim")
        for y in (-2, -1, 1, 2):
            if gate.valid(x, y):
                lit = side[0] == x and side[1] * y > 0
                c[ROW_Y[y]][sx] = ("┃" if lit else "│", "bold green" if lit else "dim")
    for (x, y), g in gate.GEARS.items():
        free = g != "R" and shifter.label(g) == "free"
        c[0 if y < 0 else 6][COL_X[x]] = (g, "bold black on green" if g == engaged else "dim" if free else "bold")
    kx, ky = knob.pos
    c[ROW_Y[ky]][COL_X[kx]] = ("◉" if bounce else "●", "bold yellow")
    legend = [f"{g} {shifter.label(g)}"[:18] for g in "1234"] + ["R previous", "N default"]
    for i in range(0, 6, 2):
        line = f" {legend[i]:<18} {legend[i + 1]}"[:W]
        c[7 + i // 2][: len(line)] = [(ch, "dim") for ch in line]
    return to_text(c)


def pos_at(x, y):
    """Nearest gate position to a mouse cell; above or below the gate counts as the column end."""
    gy = {2: -1, 3: 0, 4: 1}.get(y, -2 if y < 3 else 2)
    gx = min(range(gate.NCOL), key=lambda i: abs(COL_X[i] - x))
    return (gx, gy) if gate.valid(gx, gy) else (gx, 0)


CX, CY, R = W // 2, 8, 6  # dial centre and radius in rows; x is doubled because cells are tall


def dial_angle(g):
    i = gate.DIAL.index(g)
    return math.pi * (1 - (i + 0.5) / len(gate.DIAL))


def draw_dial(angle, engaged):
    c = grid(9)

    def put(r, a, ch, st):
        x, y = CX + round(2 * r * math.cos(a)), CY - round(r * math.sin(a))
        if 0 <= x < W and 0 <= y < 9:
            c[y][x] = (ch, st)

    for i in range(41):
        put(R, math.pi * i / 40, "·", "dim")
    for g in gate.DIAL:
        put(R + 1.5, dial_angle(g), g, "bold black on green" if g == engaged else "bold")
    deg = math.degrees(angle) % 180
    ch = "─" if deg < 22.5 or deg > 157.5 else "╱" if deg < 67.5 else "│" if deg < 112.5 else "╲"
    steep = 45 < deg < 135  # step one row at a time when steep, one column at a time when flat
    for i in range(1, 2 * W):
        r = i / math.sin(angle) if steep else i / (2 * abs(math.cos(angle)))
        if r > R - 0.8:
            break
        put(r, angle, ch, "bold red")
    c[CY][CX] = ("◆", "bold")
    return to_text(c)


def ease_out_back(t):
    return 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2


class GateView(Static):
    """Grab the knob with the mouse and drag it; it only slides along the gate."""

    dragging = False

    def on_mouse_down(self, event):
        if self.app.pixel or event.y <= 6:
            self.dragging = True
            self.capture_mouse()
            self.app.drag_to(self.app.pos_at(event.x, event.y))

    def on_mouse_move(self, event):
        if self.dragging:
            self.app.drag_to(self.app.pos_at(event.x, event.y))

    def on_mouse_up(self, event):
        if self.dragging:
            self.dragging = False
            self.release_mouse()


class AssignScreen(ModalScreen):
    """One input per gear: a model id, a /command, or blank for free."""

    BINDINGS = [("escape", "dismiss", "Cancel")]
    DEFAULT_CSS = "AssignScreen { align: center middle; } #assign { width: 40; height: auto; border: round $accent; padding: 0 1; background: $surface; }"

    def __init__(self, gears):
        super().__init__()
        self.gears = gears

    def compose(self):
        with Vertical(id="assign"):
            yield Label("Model id or /command, blank = free")
            for k in "1234":
                g = self.gears.get(k, {})
                yield Input(value=g.get("id") or g.get("command") or "", placeholder=f"gear {k}", id=f"g{k}")
            yield Button("Save", id="save", variant="primary")

    def save(self):
        out = {}
        for k in "1234":
            v = self.query_one(f"#g{k}", Input).value.strip()
            old = self.gears.get(k, {})
            if not v:
                out[k] = {"type": "none"}
            elif v.startswith("/"):
                out[k] = {"type": "command", "command": v}
            else:
                out[k] = {"type": "model", "id": v, "name": old.get("name") if old.get("id") == v else gate.pretty(v)}
        self.dismiss(out)

    def on_button_pressed(self):
        self.save()

    def on_input_submitted(self):
        self.save()


class Gearbox(App):
    CSS = """
    Screen { padding: 0; }
    #dial { height: 9; }
    #gate { height: 11; }
    #readout { height: 2; margin-top: 1; }
    #cmd { height: 1; }
    #shifts { height: 4; color: $text-muted; }
    """
    BINDINGS = [
        ("left,h", "nudge(-1, 0)", "Left"),
        ("right,l", "nudge(1, 0)", "Right"),
        ("up,k", "nudge(0, -1)", "Up"),
        ("down,j", "nudge(0, 1)", "Down"),
        *[(k, f"jump('{k.upper()}')", k) for k in "1234rn"],
        ("m", "mute", "Mute"),
        ("a", "assign", "Assign"),
        ("s", "send_now", "Send now"),
        ("c", "copy", "Copy"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, target=None):
        super().__init__()
        cfg, err = store.load_config()
        self.cfg = cfg or store.DEFAULT
        self.cfg_mtime = store.CONFIG.stat().st_mtime
        self.cli_target = target
        self.shifter = gate.Shifter(self.cfg["gears"])  # live model unknown at start, so the first shift always sends
        self.bridge = bridge.Bridge(target or self.cfg.get("target"))
        self.knob, self.engaged, self.path = gate.Knob(), "N", []
        self.angle, self.swing, self.bounce_until = dial_angle("N"), None, 0
        self.msg, self.cmd_line, self.shifts, self.busy = err or "Neutral", "", [], store.is_busy()
        self.sending = False
        self.pixel = False

    def compose(self):
        yield Static(id="dial")
        yield GateView(id="gate")
        yield Static(id="readout")
        yield Static(id="cmd")
        yield Static(id="shifts")

    def on_mount(self):
        self.pixel = self.console.color_system == "truecolor"  # else the 256-color box-drawing gate
        if self.pixel:
            self.query_one("#gate").styles.height = skin.H // 2
        self.set_interval(STEP_S, self.advance)
        self.set_interval(1 / 30, self.frame)
        self.set_interval(0.25, self.tick)
        self.set_interval(1, self.reload)
        self.redraw()

    # --- knob ---

    def check_action(self, action, parameters):
        return not isinstance(self.screen, ModalScreen)  # keys belong to the assign screen while it is open

    def action_nudge(self, dx, dy):
        self.path = []
        self.move(gate.step(self.knob.pos, dx, dy))

    def action_jump(self, g):
        self.path = gate.path(self.knob.pos, g)
        while self.path and self.cfg["reducedMotion"]:
            self.advance()

    def pos_at(self, x, y):
        return skin.pos_at(x, y) if self.pixel else pos_at(x, y)

    def drag_to(self, pos):
        self.path = []
        for p in gate.route(self.knob.pos, pos):
            self.move(p)

    def advance(self):
        if self.path:
            self.move(self.path.pop(0))

    def move(self, pos):
        g = self.knob.move(pos)
        if g:
            self.engage(g)
        self.redraw()

    def engage(self, g):
        cmd, self.msg = self.shifter.engage(g)
        self.engaged = g
        target = dial_angle(g)
        self.swing = None if self.cfg["reducedMotion"] else (self.angle, target, time.monotonic())
        self.angle = self.angle if self.swing else target
        if g != "N":
            self.bounce_until = 0 if self.cfg["reducedMotion"] else time.monotonic() + BOUNCE_S
            if self.cfg["sound"]:
                self.bell()
            stamp = datetime.now().strftime("%H:%M:%S")
            self.shifts = [f"{stamp}  {g}  {self.shifter.label(g) if g != 'R' else self.shifter.name(self.shifter.current)}"] + self.shifts[:3]
        if g == "N":
            self.set_timer(REST_S, self.rest)
        if cmd:
            self.bridge.queue(cmd)
            self.tick()
        self.save_state()

    def rest(self):
        """Still in neutral after REST_S: that is a real choice, not a pass-through."""
        if self.knob.gear != "N":
            return
        cmd, self.msg = self.shifter.rest_neutral()
        if cmd:
            self.bridge.queue(cmd)
            self.tick()
        self.save_state()
        self.redraw()

    # --- timers ---

    def frame(self):
        if self.swing:
            a, b, t0 = self.swing
            t = min(1, (time.monotonic() - t0) / SWING_S)
            self.angle = a + (b - a) * ease_out_back(t)
            self.swing = None if t == 1 else self.swing
            self.query_one("#dial", Static).update(draw_dial(self.angle, self.engaged))
        if self.bounce_until and time.monotonic() > self.bounce_until:
            self.bounce_until = 0
            self.redraw()

    def tick(self, force=False):
        busy = store.is_busy()
        if busy != self.busy:
            self.busy = busy
            self.save_state()
        if self.sending or not self.bridge.pending:
            return
        if busy and self.cfg["sendWhen"] == "idle" and not force:
            self.show(self.bridge.flush(wait=True))
            return
        self.sending = True  # sending takes ~1 s (it waits for the confirm dialog), so it runs off the UI thread
        self.cmd_line = f"sending: {self.fmt(self.bridge.pending)}"
        self.redraw()
        self.run_worker(lambda: self.call_from_thread(self.show, self.bridge.flush(wait=False)), thread=True)

    def show(self, res):
        self.sending = False
        if res:
            status, cmd = res
            if status not in ("sent", "already live", "waiting for idle", "sending"):
                self.shifter.rollback()  # Claude never got it: let the same gear fire again
            self.cmd_line = f"{status}: {self.fmt(cmd)}"
            self.redraw()

    def reload(self):
        """Hot-reload config.json when it changes on disk."""
        try:
            mtime = store.CONFIG.stat().st_mtime
        except OSError:
            return
        if mtime == self.cfg_mtime:
            return
        self.cfg_mtime = mtime
        cfg, err = store.load_config()
        if err:
            self.msg = err
        else:
            self.cfg, self.shifter.gears, self.msg = cfg, cfg["gears"], "Config reloaded"
            self.bridge.target = self.cli_target or cfg.get("target") or self.bridge.target
        self.redraw()

    # --- other keys ---

    def action_mute(self):
        self.cfg["sound"] = not self.cfg["sound"]
        self.msg = "Sound on" if self.cfg["sound"] else "Sound off"
        self.redraw()

    def action_send_now(self):
        self.tick(force=True)

    def action_copy(self):
        cmd = self.bridge.pending or self.bridge.last
        if cmd:
            self.copy_to_clipboard(self.fmt(cmd))
            self.msg = "Copied"
            self.redraw()

    def action_assign(self):
        def done(gears):
            if gears:
                store.write_json(store.CONFIG, {**self.cfg, "gears": gears})  # reload() picks it up

        self.push_screen(AssignScreen(self.cfg["gears"]), done)

    # --- output ---

    def fmt(self, cmd):
        if self.cfg["format"] == "tmux":
            return f'tmux send-keys -t {self.bridge.target or "%0"} -l "{cmd}"'
        return cmd

    def save_state(self):
        store.save_state(self.engaged, self.shifter, self.busy)

    def redraw(self):
        bounce = time.monotonic() < self.bounce_until
        self.query_one("#dial", Static).update(draw_dial(self.angle, self.engaged))
        self.query_one("#gate", Static).update((skin.draw if self.pixel else draw_gate)(self.knob, self.engaged, self.shifter, bounce))
        model = self.shifter.name(self.shifter.current) if self.shifter.current else "model unknown"
        readout = Text(model, "bold")
        if self.busy:
            readout.append("  · Claude busy", "yellow")
        readout.append(f"\n{self.msg}")
        self.query_one("#readout", Static).update(readout)
        self.query_one("#cmd", Static).update(Text(f"› {self.cmd_line}"[:W], "cyan"))
        self.query_one("#shifts", Static).update("\n".join(self.shifts))


def main():
    p = argparse.ArgumentParser(prog="gearbox", description="Six-speed model shifter for Claude Code.")
    p.add_argument("--target", help="Claude Code tmux pane id (e.g. %%3), or claude.exe PID on Windows (default: auto-detect)")
    Gearbox(p.parse_args().target).run()


if __name__ == "__main__":
    main()
