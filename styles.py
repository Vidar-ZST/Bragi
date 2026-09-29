"""Visual design tokens and typography for the Bragi desktop audio player."""

import sys
import os
import ctypes
import tkinter as tk
from tkinter import font


def enable_dpi_awareness():
    """Enable high-DPI awareness on Windows to prevent blurry scaling."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


BG_APP = "#0a0b10"
BG_SURFACE = "#12141d"
BG_SURFACE_LIGHT = "#181b26"
BG_SURFACE_HOVER = "#222636"
BG_DECK_GLASS = "#0c0e17"

BORDER_SUBTLE = "#212536"
BORDER_MUTED = "#2d334a"
BORDER_FOCUS = "#00f0ff"
BORDER_AMBER = "#f59e0b"

ACCENT_CYAN = "#00f0ff"
ACCENT_CYAN_DIM = "#0891b2"
ACCENT_AMBER = "#f59e0b"
ACCENT_AMBER_BRIGHT = "#fbbf24"
ACCENT_CORAL = "#ff3366"
ACCENT_CORAL_HOVER = "#ff5c8a"
ACCENT_EMERALD = "#10b981"

TEXT_MAIN = "#f8fafc"
TEXT_MUTED = "#94a3b8"
TEXT_SUBTLE = "#64748b"
TEXT_CYAN = "#67e8f9"
TEXT_AMBER = "#fcd34d"

ERROR_COLOR = "#f43f5e"

_SANS_FAMILY = "Segoe UI"
_MONO_FAMILY = "Consolas"


def init_fonts():
    global _SANS_FAMILY, _MONO_FAMILY
    try:
        available = font.families()
        for candidate in ("Segoe UI", "Inter", "SF Pro Display", "SF Pro Text", "Roboto", "Helvetica Neue", "Arial"):
            if candidate in available:
                _SANS_FAMILY = candidate
                break
        for mono in ("Consolas", "JetBrains Mono", "Cascadia Code", "Courier New"):
            if mono in available:
                _MONO_FAMILY = mono
                break
    except Exception:
        _SANS_FAMILY = "Segoe UI"
        _MONO_FAMILY = "Consolas"


def font_logo():
    return (_SANS_FAMILY, 9, "bold")


def font_title():
    return (_SANS_FAMILY, 12, "bold")


def font_body():
    return (_SANS_FAMILY, 9)


def font_body_bold():
    return (_SANS_FAMILY, 9, "bold")


def font_label():
    return (_SANS_FAMILY, 8, "bold")


def font_small():
    return (_SANS_FAMILY, 8)


def font_time():
    return (_MONO_FAMILY, 9, "bold")
