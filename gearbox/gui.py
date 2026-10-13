"""Desktop window: tachometer, gear readout and a brushed-metal H-gate with a drag-able ball knob.

Run: pythonw -m gearbox.gui [--target PID]
"""
import argparse
import ctypes
import math
import queue
import threading
import time
import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

from . import bridge, gate, store

W, H = 300, 610
BG, PANEL, GATE_BG = "#18181a", "#0b0b0d", "#1f1f22"
CX, CY, PR = 150, 405, 125  # gate plate centre and radius
COLS = [100, 150, 200]  # x of each gate column
REST_MS = 700  # knob still in neutral this long = pick the default model (passing through does nothing)
ROW = {y: CY + y * 37.5 for y in (-2, -1, 0, 1, 2)}  # y of each gate row
SLOT = 11  # slot half-width
try:  # draw at real pixels on scaled displays instead of letting Windows stretch a blurry bitmap
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    S = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
except (AttributeError, OSError):
    S = 1
SS = 3 * S  # image pixels per layout unit; images are drawn 3x and shrunk for smooth edges
FONT = "C:/Windows/Fonts/bahnschrift.ttf"
ICON = Path(__file__).resolve().parent.parent / "gearbox-icon.ico"


def _font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def plate_image():
    """Brushed aluminium disc with the black H-gate cut into it."""
    n = int(2 * (PR + 12) * SS)
    yy, xx = np.mgrid[0:n, 0:n] - n / 2 + .5
    r, th = np.hypot(xx, yy) / SS, np.arctan2(yy, xx)
    rng = np.random.default_rng(7)
    rings = rng.normal(0, 7, int(PR + 13))[np.clip(r.astype(int), 0, int(PR + 12))]  # concentric brush marks
    v = 178 + 38 * np.cos(2 * th + .7) + 14 * np.cos(6 * th) + rings
    v = np.where(r > PR - 5, v * (0.55 + 0.45 * (PR - r) / 5), v)  # bevelled rim
    rgb = np.clip(np.stack([v, v + 2, v + 6], -1), 0, 255).astype(np.uint8)
    alpha = (np.clip(PR - r + .5, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    o = img.size[0] / 2
    d.ellipse([o - PR * SS, o - PR * SS + 6 * SS, o + PR * SS, o + PR * SS + 6 * SS], fill=(0, 0, 0, 170))
    base = Image.new("RGBA", img.size, _hex(GATE_BG) + (255,))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6 * SS)))
    base.alpha_composite(img)

    d = ImageDraw.Draw(base)
    to = lambda x, y: ((x - CX) * SS + o, (y - CY) * SS + o)
    for dy, col, w in ((2.5, (235, 237, 242), SLOT + 1.5), (0, (6, 6, 7), SLOT)):  # light lip, then the black slot
        def bar(x0, y0, x1, y1):
            (a, b), (c, e) = to(x0 - w, y0 - w + dy), to(x1 + w, y1 + w + dy)
            d.rounded_rectangle([a, b, c, e], radius=w * SS, fill=col)
        for i, x in enumerate(COLS):
            bar(x, ROW[-2], x, ROW[2 if i < gate.NCOL - 1 else 0])
        bar(COLS[0], ROW[0], COLS[-1], ROW[0])
    return base.resize((base.size[0] // 3, base.size[1] // 3), Image.LANCZOS)


def knob_image():
    """Glossy black ball on a short chrome shaft, seen from slightly above. Anchor = slot point at (40, 64)."""
    w, h = int(80 * SS), int(92 * SS)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sx, sy, bx, by, br = (int(v * SS) for v in (40, 64, 40, 38, 25))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([bx - br + 6 * SS, sy - 14 * SS, bx + br + 6 * SS, sy + 16 * SS], fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5 * SS)))
    d.ellipse([sx - 15 * SS, sy - 10 * SS, sx + 15 * SS, sy + 10 * SS], fill=(28, 28, 30), outline=(70, 70, 74), width=int(SS))  # boot
    for i in range(int(8 * SS)):  # chrome shaft
        c = int(120 + 110 * math.sin(math.pi * i / int(8 * SS)))
        d.line([sx - 4 * SS + i, by, sx - 4 * SS + i, sy], fill=(c, c, c + 4))
    yy, xx = np.mgrid[0:2 * br, 0:2 * br] - br + .5
    r = np.hypot(xx, yy) / br
    hl = np.exp(-(((xx / br + .35) ** 2 + (yy / br + .42) ** 2) / .06))  # specular spot, top left
    rim = np.clip((r - .75) / .25, 0, 1) ** 2 * (yy > 0) * 40  # faint bounce light at the bottom
    v = 14 + 26 * (1 - r) + 225 * hl + rim
    ball = np.clip(np.stack([v, v, v + 3, (np.clip(1 - r, 0, 1 / br) * br * 255)], -1), 0, 255).astype(np.uint8)
    img.alpha_composite(Image.fromarray(ball, "RGBA"), (bx - br, by - br))
    lw, ivory = int(1.6 * SS), (232, 228, 214)  # engraved shift pattern on top of the ball
    for i, x in enumerate((-10, -3.5, 3.5, 10)):
        d.line([bx + x * SS, by - 9 * SS, bx + x * SS, by + (9 if i < 3 else 0) * SS], fill=ivory, width=lw)
    d.line([bx - 10 * SS, by, bx + 10 * SS, by], fill=ivory, width=lw)
    return img.resize((w // 3, h // 3), Image.LANCZOS)


def gauge_image(value):
    """Tachometer face with R N 1-6 and a red needle; value is a fractional index into gate.DIAL."""
    w, h = 150, 104
    img = Image.new("RGB", (int(w * SS), int(h * SS)), _hex(PANEL))
    d = ImageDraw.Draw(img)
    cx, cy, r = 72 * SS, 62 * SS, 46 * SS
    ang = lambda i: math.radians(210 - i * 240 / (len(gate.DIAL) - 1))
    d.arc([cx - r, cy - r, cx + r, cy + r], -210 + 240 * 6 / 7, 30, fill=(200, 40, 30), width=int(4 * SS))  # red zone: 6th
    d.arc([cx - r, cy - r, cx + r, cy + r], -210, -210 + 240 * 6 / 7, fill=(200, 200, 205), width=int(SS))
    f = _font(int(11 * SS))
    for i, g in enumerate(gate.DIAL):
        a = ang(i)
        for k in (0, .5) if i < len(gate.DIAL) - 1 else (0,):
            b = ang(i + k)
            ln = 8 if k == 0 else 4
            d.line([cx + r * math.cos(b), cy - r * math.sin(b), cx + (r - ln * SS) * math.cos(b), cy - (r - ln * SS) * math.sin(b)],
                   fill=(235, 235, 240), width=int(2 * SS if k == 0 else SS))
        tx, ty = cx + (r - 17 * SS) * math.cos(a), cy - (r - 17 * SS) * math.sin(a)
        d.text((tx, ty), g, font=f, fill=(225, 225, 230), anchor="mm")
    d.text((cx, cy + 26 * SS), "GEAR", font=_font(int(8 * SS)), fill=(120, 120, 128), anchor="mm")
    a = ang(value)
    d.line([cx - 8 * SS * math.cos(a), cy + 8 * SS * math.sin(a), cx + (r - 4 * SS) * math.cos(a), cy - (r - 4 * SS) * math.sin(a)],
           fill=(235, 50, 35), width=int(2 * SS))
    d.ellipse([cx - 5 * SS, cy - 5 * SS, cx + 5 * SS, cy + 5 * SS], fill=(40, 40, 44), outline=(150, 150, 155), width=int(SS))
    return img.resize((img.size[0] // 3, img.size[1] // 3), Image.LANCZOS)


def nearest_on_gate(px, py):
    """Closest point on the slots to (px, py), and the nearest gate position."""
    segs = [(COLS[i], ROW[-2], COLS[i], ROW[2 if i < gate.NCOL - 1 else 0]) for i in range(gate.NCOL)] + [(COLS[0], ROW[0], COLS[-1], ROW[0])]
    best = None
    for x0, y0, x1, y1 in segs:
        t = max(0, min(1, ((px - x0) * (x1 - x0) + (py - y0) * (y1 - y0)) / ((x1 - x0) ** 2 + (y1 - y0) ** 2)))
        q = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
        dist = math.hypot(px - q[0], py - q[1])
        if not best or dist < best[0]:
            best = (dist, q)
    qx, qy = best[1]
    gx = min(range(gate.NCOL), key=lambda i: abs(COLS[i] - qx))
    gy = min(ROW, key=lambda k: abs(ROW[k] - qy))
    return best[1], ((gx, gy) if gate.valid(gx, gy) else (gx, 0))


class Shifter:
    def __init__(self, target=None):
        cfg, err = store.load_config()
        self.cfg = cfg or store.DEFAULT
        self.cfg_mtime = store.CONFIG.stat().st_mtime
        self.cli_target = target
        self.shifter = gate.Shifter(self.cfg["gears"])
        self.bridge = bridge.Bridge(target or self.cfg.get("target"))
        self.knob, self.engaged, self.path = gate.Knob(), "N", []
        self.busy, self.sending, self.status = store.is_busy(), False, err or ""
        self.results, self.retries = queue.Queue(), 0
        self.dial, self.swing, self.dragging = gate.DIAL.index("N"), None, False

        self.root = root = tk.Tk()
        root.title("gearshift-cc")
        root.configure(bg=BG)
        root.resizable(False, False)
        if ICON.exists():
            root.iconbitmap(str(ICON))
        self.c = c = tk.Canvas(root, width=W * S, height=H * S, bg=BG, highlightthickness=0)
        c.pack()

        c.create_text(W / 2, 20, text="M O D E L   S H I F T", fill="#9a9aa2", font=("Bahnschrift SemiBold", 10))
        self._rrect(12, 38, W - 12, 158, 12, PANEL, "#2c2c31")
        self.gauge = c.create_image(18, 46, anchor="nw")
        self.big = c.create_text(225, 84, fill="#f4f4f6", font=("Bahnschrift SemiBold", 46))
        self.name = c.create_text(225, 132, fill="#e6e6ea", font=("Bahnschrift SemiBold", 11))
        self.dot = c.create_oval(16, 170, 24, 178, outline="")
        self.target = c.create_text(30, 174, anchor="w", fill="#c8c8ce", font=("Consolas", 9))
        self.cmd = c.create_text(16, 194, anchor="w", fill="#8a8a92", font=("Consolas", 9))

        self._rrect(12, 210, W - 12, H - 12, 14, GATE_BG, "#2c2c31")
        self.plate = ImageTk.PhotoImage(plate_image())
        c.create_image(CX, CY + 3, image=self.plate)
        self.knob_img = ImageTk.PhotoImage(knob_image())
        self.at = list(self.px(self.knob.pos))  # knob position on screen, eased toward the logical position
        self.knob_item = c.create_image(*self.at, image=self.knob_img, anchor="nw")
        self.labels = {}
        for (x, y), g in gate.GEARS.items():
            ny, ty = (232, 249) if y < 0 else (558, 575)  # numeral, then name under it
            self.labels[g] = (c.create_text(COLS[x], ny, font=("Bahnschrift SemiBold", 15), tags=g),
                              c.create_text(COLS[x], ty, fill="#8d8d95", font=("Bahnschrift", 8), tags=g))
            c.tag_bind(g, "<Button-1>", lambda e, g=g: self.jump(g))
        c.create_text(66, ROW[0], text="N", fill="#8d8d95", font=("Bahnschrift SemiBold", 12))

        c.bind("<ButtonPress-1>", self.press)
        c.bind("<B1-Motion>", self.drag)
        c.bind("<ButtonRelease-1>", self.release)
        for keys, fn in ((("Left", "h"), lambda: self.nudge(-1, 0)), (("Right", "l"), lambda: self.nudge(1, 0)),
                         (("Up", "k"), lambda: self.nudge(0, -1)), (("Down", "j"), lambda: self.nudge(0, 1)),
                         (("s",), lambda: self.tick(force=True)), (("q", "Escape"), root.destroy),
                         (("m",), self.mute)):
            for k in keys:
                root.bind(f"<KeyPress-{k}>", lambda e, fn=fn: fn())
        for k in "1234rn":
            root.bind(f"<KeyPress-{k}>", lambda e, g=k.upper(): self.jump(g))

        c.scale("all", 0, 0, S, S)  # layout is in units; the canvas is in real pixels
        self.redraw()
        self.loop(self.advance, 110)
        self.loop(self.frame, 16)
        self.loop(self.tick, 250)
        self.loop(self.reload, 1000)

    def _rrect(self, x0, y0, x1, y1, r, fill, outline):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        self.c.create_polygon(pts, smooth=True, fill=fill, outline=outline)

    def loop(self, fn, ms):
        def run():
            fn()
            self.root.after(ms, run)
        self.root.after(ms, run)

    @staticmethod
    def px(pos):
        return COLS[pos[0]] - 40, ROW[pos[1]] - 64  # knob image anchor offset

    # --- knob ---

    def nudge(self, dx, dy):
        self.path = []
        self.move(gate.step(self.knob.pos, dx, dy))

    def jump(self, g):
        self.path = gate.path(self.knob.pos, g)
        while self.path and self.cfg["reducedMotion"]:
            self.advance()

    def advance(self):
        if self.path:
            self.move(self.path.pop(0))

    def move(self, pos):
        g = self.knob.move(pos)
        if g:
            self.engage(g)

    def press(self, e):
        if math.hypot(e.x / S - CX, e.y / S - CY) <= PR:
            self.dragging, self.path = True, []
            self.drag(e)

    def drag(self, e):
        if not self.dragging:
            return
        (qx, qy), pos = nearest_on_gate(e.x / S, e.y / S)
        for p in gate.route(self.knob.pos, pos):
            self.move(p)
        self.at = [qx - 40, qy - 64]  # follow the hand, along the slot

    def release(self, e):
        self.dragging = False  # frame() eases the knob onto its gate position

    def engage(self, g):
        cmd, self.status = self.shifter.engage(g)
        self.engaged = g
        target = gate.DIAL.index(g)
        self.swing = None if self.cfg["reducedMotion"] else (self.dial, target, time.monotonic())
        self.dial = self.dial if self.swing else target
        if g != "N" and self.cfg["sound"]:
            self.root.bell()
        store.log(f"engage {g}: {cmd or self.status}")
        if g == "N":
            self.root.after(REST_MS, self.rest)
        if cmd:
            self.bridge.queue(cmd)
            self.tick()
        store.save_state(self.engaged, self.shifter, self.busy)
        self.redraw()

    def rest(self):
        """Still in neutral after REST_MS: that is a real choice, not a pass-through."""
        if self.knob.gear != "N":
            return
        cmd, self.status = self.shifter.rest_neutral()
        store.log(f"rest N: {cmd or self.status}")
        if cmd:
            self.bridge.queue(cmd)
            self.tick()
        store.save_state(self.engaged, self.shifter, self.busy)
        self.redraw()

    # --- timers ---

    def frame(self):
        if not self.dragging:
            tx, ty = self.px(self.knob.pos)
            k = 1 if self.cfg["reducedMotion"] else .35
            self.at = [self.at[0] + (tx - self.at[0]) * k, self.at[1] + (ty - self.at[1]) * k]
        self.c.coords(self.knob_item, self.at[0] * S, self.at[1] * S)
        if self.swing:
            a, b, t0 = self.swing
            t = min(1, (time.monotonic() - t0) / .45)
            self.dial = a + (b - a) * (1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2)  # ease out with overshoot
            self.swing = None if t == 1 else self.swing
            self.draw_gauge()

    def tick(self, force=False):
        busy = store.is_busy()
        if busy != self.busy:
            self.busy = busy
            store.save_state(self.engaged, self.shifter, busy)
            self.redraw()
        while not self.results.empty():  # worker results, handled on the UI thread
            self.sending = False
            self.done(self.results.get())
        if self.sending or not self.bridge.pending:
            return
        if busy and self.cfg["sendWhen"] == "idle" and not force:
            self.show(self.bridge.flush(wait=True))
            return
        self.sending = True  # the console helper is a subprocess, so it runs off the UI thread
        self.show(("sending", self.bridge.pending))

        def work():
            try:
                self.results.put(self.bridge.flush(wait=False))
            except Exception as e:  # noqa: BLE001 - whatever happens, the flag must clear
                self.results.put((f"error: {e}", self.bridge.last))
            self.root.after(0, self.tick)

        threading.Thread(target=work, daemon=True).start()

    def done(self, res):
        store.log(f"result {res}")
        if res and res[0] not in ("sent", "already live"):  # Claude never got it
            self.retries += 1
            if self.retries <= 2:
                self.bridge.queue(res[1])  # the next tick tries again
                res = (f"retry {self.retries}", res[1])
            else:
                self.shifter.rollback()  # give up; pulling out and back into the gear sends it again
                res = (res[0] + " (shift again)", res[1])
        else:
            self.retries = 0
        self.show(res)

    def show(self, res):
        if res:
            status, cmd = res
            self.status = f"{cmd} \u2192 {status}"
            self.redraw()

    def reload(self):
        try:
            mtime = store.CONFIG.stat().st_mtime
        except OSError:
            return
        if mtime == self.cfg_mtime:
            return
        self.cfg_mtime = mtime
        cfg, err = store.load_config()
        if err:
            self.status = err
        else:
            self.cfg, self.shifter.gears, self.status = cfg, cfg["gears"], "config reloaded"
            self.bridge.target = self.cli_target or cfg.get("target") or self.bridge.target
        self.redraw()

    def mute(self):
        self.cfg["sound"] = not self.cfg["sound"]
        self.status = "sound on" if self.cfg["sound"] else "sound off"
        self.redraw()

    # --- output ---

    def draw_gauge(self):
        self.gauge_img = ImageTk.PhotoImage(gauge_image(self.dial))
        self.c.itemconfigure(self.gauge, image=self.gauge_img)

    def redraw(self):
        c, cur = self.c, self.shifter.current
        self.draw_gauge()
        c.itemconfigure(self.big, text=self.engaged)
        c.itemconfigure(self.name, text=(self.shifter.name(cur) if cur else "NEUTRAL" if self.engaged == "N" else "MODEL UNKNOWN").upper())
        t = self.bridge.target
        c.itemconfigure(self.dot, fill="#e0a020" if self.busy else "#3ccf5a" if t else "#55555c")
        c.itemconfigure(self.target, text=(f"claude pid {t}" if bridge.WINDOWS else f"claude {t}") + ("  \u00b7 busy" if self.busy else "") if t else "no claude session found")
        c.itemconfigure(self.cmd, text=self.status[:44])
        for g, (num, name) in self.labels.items():
            label = "PREVIOUS" if g == "R" else self.shifter.label(g).upper()
            c.itemconfigure(num, text=g, fill="#e8392a" if g == self.engaged else "#f0f0f2" if label != "FREE" else "#66666e")
            c.itemconfigure(name, text=label.split(" ")[0] if len(label) > 8 else label)  # SONNET 5.5 -> SONNET, columns are narrow


def main():
    p = argparse.ArgumentParser(prog="gearshift-cc", description="Six-speed model shifter for Claude Code (window).")
    p.add_argument("--target", help="claude.exe PID on Windows, tmux pane id elsewhere (default: auto-detect)")
    Shifter(p.parse_args().target).root.mainloop()


if __name__ == "__main__":
    main()
