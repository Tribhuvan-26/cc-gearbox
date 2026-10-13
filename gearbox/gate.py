"""Gate geometry, knob state machine and shift decisions. No UI, no I/O."""

# A position is (x, y): x is the column 0..3, y runs -2 (top end) .. 2 (bottom end), y == 0 is the neutral lane.
GEARS = {(0, -2): "1", (0, 2): "2", (1, -2): "3", (1, 2): "4", (2, -2): "R"}
NCOL = 3  # the last column holds only R, on top
POS = {g: p for p, g in GEARS.items()}
DIAL = ["R", "N", "1", "2", "3", "4"]  # left to right on the dial
DEFAULT = "default"  # Claude Code's own recommended model; resting in neutral selects it


def valid(x, y):
    return 0 <= x < NCOL and -2 <= y <= 2 and (y <= 0 or x < NCOL - 1)  # the R column has no bottom half


def gear_at(pos):
    return GEARS.get(pos) or ("N" if pos[1] == 0 else "transit")


def step(pos, dx, dy):
    """One arrow-key move. Sideways only in the lane; anything off the gate is refused."""
    x, y = pos
    if dx and y:
        return pos
    nxt = (x + dx, y + dy)
    return nxt if valid(*nxt) else pos


def path(pos, gear):
    """Positions visited going from pos to gear, one step each, through the neutral lane."""
    return route(pos, POS.get(gear, (pos[0], 0)))  # N = the lane at the current column


def route(pos, target):
    """Positions visited going from pos to any gate position, one step each, through the neutral lane."""
    x, y = pos
    tx, ty = target
    out = []
    if tx != x or y * ty < 0:  # other column, or other half of this one: back to the lane first
        while y:
            y -= 1 if y > 0 else -1
            out.append((x, y))
        while x != tx:
            x += 1 if tx > x else -1
            out.append((x, y))
    while y != ty:
        y += 1 if ty > y else -1
        out.append((x, y))
    return out


class Knob:
    def __init__(self, pos=(1, 0)):
        self.pos, self.gear = pos, gear_at(pos)

    def move(self, pos):
        """Move the knob; return the gear if this move engaged a new one, else None."""
        g = gear_at(pos)
        fired = g if g not in (self.gear, "transit") else None
        self.pos, self.gear = pos, g
        return fired


def pretty(model_id):
    """claude-opus-5-5 -> Opus 5.5"""
    if model_id == DEFAULT:
        return "Default"
    family, *ver = model_id.removeprefix("claude-").split("-")
    return f"{family.title()} {'.'.join(ver)}".strip()


class Shifter:
    """Turns engaged gears into commands. Tracks the current and previous model."""

    def __init__(self, gears, current=None, previous=None):
        self.gears, self.current, self.previous = gears, current, previous
        self._undo = (previous, current)

    def name(self, model_id):
        for g in self.gears.values():
            if g.get("id") == model_id:
                return g.get("name") or pretty(model_id)
        return pretty(model_id) if model_id else "unknown"

    def label(self, gear):
        g = self.gears.get(gear, {})
        if g.get("type") == "model":
            return self.name(g["id"])
        return g.get("command") or "free"

    def engage(self, gear):
        """Return (command or None, message)."""
        if gear == "N":
            return None, "Neutral"
        if gear == "R":
            if not self.previous:
                return None, "Nothing to reverse"
            return self._to(self.previous), "Reverse"
        g = self.gears.get(gear, {})
        if g.get("type") == "model":
            if g["id"] == self.current:
                return None, f"Gear {gear}, already on {self.name(g['id'])}"
            return self._to(g["id"]), f"Gear {gear}"
        if g.get("type") == "command":
            return g["command"], f"Gear {gear}"
        return None, "Free gear"

    def rest_neutral(self):
        """The knob stayed in neutral: hand the choice back to Claude Code. Passing through neutral does nothing."""
        if self.current == DEFAULT:
            return None, "Neutral, default model"
        return self._to(DEFAULT), "Neutral: default model"

    def _to(self, model_id):
        self._undo = (self.previous, self.current)
        self.previous, self.current = self.current, model_id
        return f"/model {model_id}"

    def rollback(self):
        """The last _to() never reached Claude: forget it, so the same gear can fire again."""
        self.previous, self.current = self._undo
