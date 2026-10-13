"""Run: python test_gearbox.py  (plain asserts, no framework)"""
import itertools
import json
import os
import random
import tempfile

os.environ["GEARBOX_HOME"] = tempfile.mkdtemp()

from gearbox import bridge, gate, store  # noqa: E402

ARROWS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
ALL = ["1", "2", "3", "4", "R", "N"]


def test_reachable_by_arrows():
    seen, todo = {(1, 0)}, [(1, 0)]
    while todo:
        p = todo.pop()
        for d in ARROWS:
            n = gate.step(p, *d)
            if n not in seen:
                seen.add(n)
                todo.append(n)
    assert {gate.gear_at(p) for p in seen} >= set(ALL)


def test_knob_never_leaves_gate():
    rnd = random.Random(1)
    p = (1, 0)
    for _ in range(5000):
        p = gate.step(p, *rnd.choice(ARROWS))
        assert gate.valid(*p), p


def test_jump_paths():
    for a, b in itertools.product(ALL, ALL):
        k = gate.Knob(gate.POS.get(a, (1, 0)))
        fired = [g for p in gate.path(k.pos, b) for g in [k.move(p)] if g]
        assert k.gear == b, (a, b)
        assert fired.count(b) == (a != b), (a, b, fired)
        assert all(gate.valid(*p) and abs(p[0]) <= 3 for p in gate.path(gate.POS.get(a, (1, 0)), b))


def test_fire_once_and_again_after_pullout():
    k = gate.Knob((0, 0))
    assert [k.move(p) for p in [(0, -1), (0, -2)]] == [None, "1"]
    assert k.move((0, -2)) is None
    assert [k.move(p) for p in [(0, -1), (0, -2)]] == [None, "1"]


def shifter():
    return gate.Shifter(store.DEFAULT["gears"])


def test_shifter_rules():
    s = shifter()
    assert s.engage("R") == (None, "Nothing to reverse")
    assert s.engage("N")[0] is None
    assert s.engage("2")[0] == "/model claude-sonnet-5-5"
    assert s.engage("2")[0] is None  # already on it: no resend
    assert s.engage("3")[0] == "/model claude-opus-5-5"
    assert s.engage("R")[0] == "/model claude-sonnet-5-5"
    assert s.engage("R")[0] == "/model claude-opus-5-5"  # reverse twice = back where we started
    assert s.name("claude-opus-5-5") == "Opus 5.5" and gate.pretty("claude-haiku-5-5") == "Haiku 5.5"


def test_bridge_queue():
    sent = []
    b = bridge.Bridge(target="%9", last="/model claude-sonnet-5-5")
    b.send = lambda t: sent.append(t)
    b.queue("/model claude-opus-5-5")
    b.queue("/model claude-haiku-5-5")  # latest wins
    assert b.flush(wait=True) == ("waiting for idle", "/model claude-haiku-5-5") and not sent
    assert b.flush(wait=False) == ("sent", "/model claude-haiku-5-5")
    assert b.flush(wait=False) is None and sent == ["/model claude-haiku-5-5"]
    b.queue("/model claude-haiku-5-5")  # A -> B -> A while busy ends where we are: no send
    assert b.flush(wait=False)[0] == "already live" and len(sent) == 1


def test_bridge_error_dropped():
    b = bridge.Bridge(target="%9")
    b.send = lambda t: "tmux: can't find pane: %9"
    b.queue("/model x")
    assert b.flush(wait=False)[0].startswith("tmux") and b.pending is None


def test_config():
    cfg, err = store.load_config()
    assert err is None and cfg["gears"]["1"]["id"] == "claude-haiku-5-5"
    assert store.validate({"gears": {"7": {"type": "none"}}}) == "unknown gear '7'"
    assert store.validate({"gears": {"1": {"type": "model"}}}) == "gear 1: missing id"
    assert store.validate({"sendWhen": "later"})
    store.CONFIG.write_text("{bad")
    assert store.load_config()[0] is None
    store.write_json(store.STATE, {"gear": "3"})
    assert json.loads(store.STATE.read_text())["gear"] == "3" and not list(store.HOME.glob("*.tmp"))


def test_failed_send_rolls_back():
    sh = gate.Shifter(store.DEFAULT["gears"])
    sh.rollback()  # nothing sent yet: harmless
    assert sh.engage("2")[0] == "/model claude-sonnet-5-5"
    assert sh.engage("2")[0] is None  # already on it
    sh.rollback()  # the send failed
    assert (sh.current, sh.previous) == (None, None)
    assert sh.engage("2")[0] == "/model claude-sonnet-5-5"  # same gear fires again


def test_neutral_rest_vs_pass_through():
    sh = gate.Shifter(store.DEFAULT["gears"])
    assert sh.engage("N") == (None, "Neutral")  # passing through: nothing
    assert sh.rest_neutral()[0] == "/model default"  # staying: Claude Code's default model
    assert sh.rest_neutral()[0] is None  # already on it
    assert sh.engage("R")[0] is None and sh.engage("3")[0] == "/model claude-opus-5-5"
    assert sh.engage("R")[0] == "/model default"  # reverse works to/from default


def test_drag_projects_onto_slots():
    from gearbox import gui
    (qx, qy), pos = gui.nearest_on_gate(gui.COLS[1] + 9, gui.ROW[-2] - 30)  # above and right of gear 3's slot
    assert (qx, pos) == (gui.COLS[1], (1, -2))
    assert gui.nearest_on_gate(gui.COLS[2] + 5, gui.ROW[0] + 20)[1] == (2, 0)  # below R: its column stops at the lane
    assert gui.nearest_on_gate(gui.CX, gui.ROW[0] + 3)[1][1] == 0  # just off the lane snaps to neutral


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
