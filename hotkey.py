"""
Global hotkey manager.
Uses native Windows Win32 RegisterHotKey API with active keyboard layout awareness
(VkKeyScanW) so that international and Hungarian keyboards (e.g. 'ú', 'ö', 'ő')
work seamlessly alongside standard combinations (e.g. 'ctrl+shift+p', 'f9').
Falls back to the keyboard library if needed.
"""

import sys
import threading
import time
from typing import Callable, Optional
import ctypes
import ctypes.wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_MAP = {
    'backspace': 0x08, 'tab': 0x09, 'clear': 0x0C, 'return': 0x0D, 'enter': 0x0D,
    'pause': 0x13, 'capslock': 0x14, 'escape': 0x1B, 'esc': 0x1B, 'space': 0x20,
    'pageup': 0x21, 'pagedown': 0x22, 'end': 0x23, 'home': 0x24,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'select': 0x29, 'print': 0x2A, 'execute': 0x2B, 'printscreen': 0x2C, 'snapshot': 0x2C,
    'insert': 0x2D, 'delete': 0x2E, 'del': 0x2E, 'help': 0x2F,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46,
    'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C,
    'm': 0x4D, 'n': 0x4E, 'o': 0x4F, 'p': 0x50, 'q': 0x51, 'r': 0x52,
    's': 0x53, 't': 0x54, 'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58,
    'y': 0x59, 'z': 0x5A,
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62, 'numpad3': 0x63, 'numpad4': 0x64,
    'numpad5': 0x65, 'numpad6': 0x66, 'numpad7': 0x67, 'numpad8': 0x68, 'numpad9': 0x69,
    'multiply': 0x6A, 'add': 0x6B, 'separator': 0x6C, 'subtract': 0x6D, 'decimal': 0x6E, 'divide': 0x6F,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'f13': 0x7C, 'f14': 0x7D, 'f15': 0x7E, 'f16': 0x7F, 'f17': 0x80, 'f18': 0x81,
    'f19': 0x82, 'f20': 0x83, 'f21': 0x84, 'f22': 0x85, 'f23': 0x86, 'f24': 0x87,
    'numlock': 0x90, 'scrolllock': 0x91
}


def parse_hotkey_to_vk(hotkey_str: str):
    """
    Parse hotkey string like 'ctrl+shift+p', 'f9', or 'ú' into (modifiers, vk_code).
    Uses VkKeyScanW on Windows to resolve the exact physical virtual key on the active
    keyboard layout (e.g. Hungarian 'ú' -> 0xDD, not 0xDA).
    """
    parts = [p.strip().lower() for p in hotkey_str.split('+') if p.strip()]
    mods = 0
    vk = 0
    for p in parts:
        if p in ('ctrl', 'control'):
            mods |= MOD_CONTROL
        elif p in ('shift',):
            mods |= MOD_SHIFT
        elif p in ('alt',):
            mods |= MOD_ALT
        elif p in ('win', 'windows'):
            mods |= MOD_WIN
        elif p in VK_MAP:
            vk = VK_MAP[p]
        elif p.startswith('f') and p[1:].isdigit():
            num = int(p[1:])
            if 1 <= num <= 24:
                vk = 0x70 + (num - 1)
        elif len(p) == 1:
            if sys.platform == "win32":
                # Look up physical virtual-key for current keyboard layout
                res = ctypes.windll.user32.VkKeyScanW(ord(p))
                if res != -1 and (res & 0xFF) != 0:
                    vk = res & 0xFF
                    # Check if key requires Shift on this layout
                    shift_state = (res >> 8) & 0xFF
                    if shift_state & 1:
                        mods |= MOD_SHIFT
                    if shift_state & 2:
                        mods |= MOD_CONTROL
                    if shift_state & 4:
                        mods |= MOD_ALT
                else:
                    vk = ord(p.upper())
            else:
                vk = ord(p.upper())
        elif p in ('plus', '+'):
            vk = 0xBB
        elif p in ('minus', '-'):
            vk = 0xBD
        elif p in ('comma', ','):
            vk = 0xBC
        elif p in ('period', '.'):
            vk = 0xBE

    return (mods | MOD_NOREPEAT, vk)


class Win32HotkeyWorker(threading.Thread):
    """Background thread with Win32 message pump for RegisterHotKey."""

    def __init__(self, modifiers: int, vk: int, callback: Callable[[], None]):
        super().__init__(daemon=True)
        self.modifiers = modifiers
        self.vk = vk
        self.callback = callback
        self.thread_id = None
        self.registered = False
        self.reg_event = threading.Event()

    def run(self):
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = ctypes.wintypes.MSG()
        ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        self.registered = bool(
            ctypes.windll.user32.RegisterHotKey(None, 1001, self.modifiers, self.vk)
        )
        self.reg_event.set()

        if not self.registered:
            return

        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == 1001:
                try:
                    self.callback()
                except Exception as e:
                    print(f"[Win32 Hotkey Exception] {e}")
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        ctypes.windll.user32.UnregisterHotKey(None, 1001)

    def stop(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


class HotkeyManager:
    """Manages system-wide global hotkey registration and recording."""

    def __init__(self, callback: Optional[Callable[[], None]] = None):
        self.callback = callback
        self.current_hotkey: Optional[str] = None
        self._win32_worker: Optional[Win32HotkeyWorker] = None
        self._lock = threading.Lock()

    def register(self, hotkey_str: str, callback: Optional[Callable[[], None]] = None) -> bool:
        """Register a global hotkey combination (e.g. 'ctrl+shift+p', 'ú', 'f9')."""
        if callback:
            self.callback = callback

        with self._lock:
            self._unregister_locked()

            clean_str = (hotkey_str or "").strip().lower()
            if not clean_str:
                return False

            # On Windows, use native RegisterHotKey with layout-aware VK mapping
            if sys.platform == "win32":
                try:
                    mods, vk = parse_hotkey_to_vk(clean_str)
                    if vk:
                        worker = Win32HotkeyWorker(mods, vk, self._on_triggered)
                        worker.start()
                        worker.reg_event.wait(timeout=1.0)
                        if worker.registered:
                            self._win32_worker = worker
                            self.current_hotkey = clean_str
                            return True
                        else:
                            worker.stop()
                except Exception as e:
                    print(f"[Hotkey Win32 Error] {e}")

            try:
                import keyboard
                keyboard.add_hotkey(clean_str, self._on_triggered)
                self.current_hotkey = clean_str
                return True
            except Exception as e:
                print(f"[Hotkey Fallback Error] {e}")
                self.current_hotkey = None
                return False

    def _on_triggered(self):
        if self.callback:
            self.callback()

    def unregister(self):
        """Unregister the currently active global hotkey."""
        with self._lock:
            self._unregister_locked()

    def _unregister_locked(self):
        if self._win32_worker:
            try:
                self._win32_worker.stop()
            except Exception:
                pass
            self._win32_worker = None

        if self.current_hotkey:
            try:
                import keyboard
                keyboard.remove_hotkey(self.current_hotkey)
            except Exception:
                pass

        self.current_hotkey = None

    @staticmethod
    def record_hotkey() -> str:
        """Capture the next key combination pressed by user."""
        try:
            import keyboard
            return keyboard.read_hotkey(suppress=False)
        except Exception:
            return ""
