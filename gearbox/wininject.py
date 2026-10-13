"""Windows: type text into another process's console, then press Enter. No focus stealing.

Run as a detached helper (it must not own a console): python wininject.py <pid> <text> [--confirm]
"""
import ctypes
import sys
import time
from ctypes import wintypes as w

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = w.HANDLE
WAIT_S = 600  # how long to watch for Claude Code's "Switch model?" dialog; with no dialog nothing is pressed


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", w.BOOL), ("wRepeatCount", w.WORD), ("wVirtualKeyCode", w.WORD),
                ("wVirtualScanCode", w.WORD), ("UnicodeChar", w.WCHAR), ("dwControlKeyState", w.DWORD)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", w.WORD), ("Event", KEY_EVENT_RECORD)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [(n, w.SHORT) for n in ("Left", "Top", "Right", "Bottom")]


class CSBI(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("cursor", w.DWORD), ("attr", w.WORD), ("window", SMALL_RECT), ("maxsize", w.DWORD)]


def keys(text):
    recs = []
    for ch in text:
        vk = 0x0D if ch == "\r" else ctypes.windll.user32.VkKeyScanW(ch) & 0xFF
        for down in (True, False):
            recs.append(INPUT_RECORD(1, KEY_EVENT_RECORD(down, 1, vk, 0, ch, 0)))  # 1 = KEY_EVENT
    return (INPUT_RECORD * len(recs))(*recs)


def write(handle, text):
    buf, n = keys(text), w.DWORD()
    if not k32.WriteConsoleInputW(handle, buf, len(buf), ctypes.byref(n)):
        raise ctypes.WinError(ctypes.get_last_error())


def screen(out):
    """Text of the visible console window."""
    info = CSBI()
    k32.GetConsoleScreenBufferInfo(out, ctypes.byref(info))
    width, win = info.size & 0xFFFF, info.window
    lines = []
    for row in range(win.Top, win.Bottom + 1):
        buf, n = ctypes.create_unicode_buffer(width), w.DWORD()
        k32.ReadConsoleOutputCharacterW(out, buf, width, w.DWORD(row << 16), ctypes.byref(n))
        lines.append(buf.value)
    return "\n".join(lines)


def confirm_dialog(inp, out):
    """Answer Claude Code's "Switch model?" dialog with Yes whenever it shows, up to WAIT_S.

    While Claude is busy the typed /model waits in its queue, so the dialog can show minutes later.
    "1" picks "Yes, switch"; if the dialog is still up, Enter (Yes is the default) until it closes.
    """
    end, key, presses = time.time() + WAIT_S, "1", 0
    while time.time() < end and presses < 4:  # cap: never keep pressing if the text lingers on screen
        if "witch model?" in screen(out):
            write(inp, key)
            key, presses = "\r", presses + 1
            time.sleep(0.15)
        elif key == "\r":
            return  # dialog answered and gone
        else:
            time.sleep(0.03)


def main(pid, text, confirm=False):
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        raise ctypes.WinError(ctypes.get_last_error())
    h = k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)  # read|write, share read|write, OPEN_EXISTING
    if h in (None, w.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    write(h, text)
    time.sleep(0.03)  # Enter as a separate burst, so it is a key press and not part of a paste
    write(h, "\r")
    print("typed", flush=True)  # the shifter can report "sent" now; the rest is the dialog watcher
    if confirm:
        confirm_dialog(h, k32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None))


if __name__ == "__main__":
    try:
        main(int(sys.argv[1]), sys.argv[2], "--confirm" in sys.argv[3:])
    except OSError as e:
        sys.exit(f"inject: {e}")
