"""Chrome plate, black gate and leather knob on a pixel canvas, printed with half blocks (2 pixels per cell)."""
import math
from functools import cache

from rich.style import Style
from rich.text import Text

from . import gate

W, H = 42, 44  # pixels; H/2 text rows
COL_X = [10, 21, 32]  # pixel column of each gate column (also its text column)
PY = {-2: 10, -1: 16, 0: 22, 1: 28, 2: 34}  # pixel row of each gate y

LEATHER, TAN, IVORY = (20, 41, 31), (201, 178, 124), (239, 230, 207)
BLACK, EDGE = (5, 6, 7), (42, 46, 51)
KNOB, AMBER = (27, 20, 15), (255, 178, 61)
NUMERAL, NAME, RED = "#2b3036", "#454b52", "#c8321f"
SLOT_R, EDGE_R = 1.7, 2.5  # slot half-width and slot-plus-edge half-width, in pixels


def _seg(px, py, x0, y0, x1, y1):
    t = max(0, min(1, ((px - x0) * (x1 - x0) + (py - y0) * (y1 - y0)) / ((x1 - x0) ** 2 + (y1 - y0) ** 2 or 1)))
    return math.hypot(px - (x0 + t * (x1 - x0)), py - (y0 + t * (y1 - y0)))


def _chrome(x, y):
    d = (x * 0.6 + y * 0.4) / (W * 0.6 + H * 0.4)  # diagonal position 0..1
    v = 150 + 25 * d + 70 * math.exp(-((d - 0.3) / 0.07) ** 2) + 55 * math.exp(-((d - 0.72) / 0.06) ** 2)
    v = min(235, v)
    return (int(v), int(v + 3), int(v + 8))


@cache
def _plate():
    """The static part: leather margin with stitching, chrome, screws, the gate slots."""
    segs = [(COL_X[x] + .5, PY[-2] + .5, COL_X[x] + .5, PY[2 if x < gate.NCOL - 1 else 0] + .5) for x in range(gate.NCOL)]
    segs.append((COL_X[0] + .5, PY[0] + .5, COL_X[-1] + .5, PY[0] + .5))
    img = [[LEATHER] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if x in (0, W - 1) or y in (0, H - 1):
                img[y][x] = TAN if (x + y) % 3 == 0 else LEATHER  # dashed stitching
            elif (x in (1, W - 2)) and (y in (1, H - 2)):
                continue  # rounded plate corners
            else:
                d = min(_seg(x + .5, y + .5, *s) for s in segs)
                img[y][x] = BLACK if d <= SLOT_R else EDGE if d <= EDGE_R else _chrome(x, y)
    for sx, sy in [(4, 4), (W - 5, 4), (4, H - 5), (W - 5, H - 5)]:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            img[sy + dy][sx + dx] = (74, 79, 85)
        img[sy][sx] = (170, 176, 184)
    return img


def _knob(img, kx, ky, bounce):
    cx, cy = kx + .5, ky + .5
    for y in range(ky - 5, ky + 6):  # soft shadow, down and right
        for x in range(kx - 5, kx + 6):
            if 0 < x < W - 1 and 0 < y < H - 1 and math.hypot(x + .5 - cx - .8, y + .5 - cy - 1.2) <= 3.9:
                img[y][x] = tuple(int(c * .6) for c in img[y][x])
    for y in range(ky - 4, ky + 5):
        for x in range(kx - 4, kx + 5):
            if not (0 < x < W - 1 and 0 < y < H - 1):
                continue
            d = math.hypot(x + .5 - cx, y + .5 - cy)
            if d <= 3.6:
                lit = int(215 - 25 * (y - ky + 3.6) / 7)
                img[y][x] = AMBER if bounce else (lit, lit + 3, lit + 8)
            if d <= 2.8:
                img[y][x] = KNOB
    for dy in (-1, 0, 1):  # ivory H: two uprights and a crossbar
        img[ky + dy][kx - 1] = img[ky + dy][kx + 1] = IVORY
    img[ky][kx] = IVORY


def _hex(c):
    return "#%02x%02x%02x" % c


def draw(knob, engaged, shifter, bounce):
    img = [row[:] for row in _plate()]
    kx, ky = knob.pos
    _knob(img, COL_X[kx], PY[ky], bounce)
    lab = {}  # (text row, text col) -> (char, color, bold)

    def put(row, col, s, color, bold=False):
        for i, ch in enumerate(s):
            lab[row, col + i] = (ch, color, bold)

    for (x, y), g in gate.GEARS.items():
        name = ("Previous" if g == "R" else shifter.label(g))[:10]
        top = y < 0
        put(1 if top else 20, COL_X[x], g, RED if g == engaged else NUMERAL, True)
        put(2 if top else 19, COL_X[x] - len(name) // 2, name, NAME)
    put(11, 4, "N", RED if engaged == "N" else NUMERAL, True)
    put(15, 31, "4-speed", NUMERAL, True)
    put(16, 29, "Claude Code", NAME)

    t = Text()
    for r in range(H // 2):
        for c in range(W):
            top, bot = img[2 * r][c], img[2 * r + 1][c]
            if (r, c) in lab:
                ch, color, bold = lab[r, c]
                bg = tuple((a + b) // 2 for a, b in zip(top, bot))
                t.append(ch, Style(color=color, bgcolor=_hex(bg), bold=bold))
            else:
                t.append("▀", Style(color=_hex(top), bgcolor=_hex(bot)))
        if r < H // 2 - 1:
            t.append("\n")
    return t


def pos_at(x, y):
    """Nearest gate position to a mouse cell (x, y in text cells)."""
    gx = min(range(gate.NCOL), key=lambda i: abs(COL_X[i] - x))
    gy = min(PY, key=lambda k: abs(PY[k] - (2 * y + 1)))
    return (gx, gy) if gate.valid(gx, gy) else (gx, 0)
