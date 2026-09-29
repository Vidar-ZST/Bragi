"""
Main application file for the Retro-Modern Hi-Fi YouTube Audio Player.
Combines vintage Japanese studio master decks (Braun, Sony, Nakamichi) with
sleek modern cyber-OLED dark mode and fluid illuminated accents.

Features:
- Live animated 11-band stereo graphic spectrum / VU meter
- Clean static album artwork frame with blurred backdrop banner & scanlines
- Precision VFD fluorescent timeline scrubber with digital timecodes
- Chamfered rack-mount search and link input bays
- Tactile transport plate with glowing neon-coral play button
- Borderless resizable window with custom chrome, min/max bounds & fluid dragging
- Win32 WS_EX_APPWINDOW extended style for Taskbar & Alt-Tab visibility
- Native Win32 RegisterHotKey global overlay toggle
- System tray integration with runtime Pillow emblem (pystray)
- mpv audio playback via JSON IPC (player.py)
"""

import sys
import os
import io
import json
import time
import math
import random
import queue
import ctypes
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional, Dict, Any, List
from PIL import Image, ImageTk, ImageFilter, ImageDraw
import requests

import styles
import icons
from tray import SystemTrayManager
from hotkey import HotkeyManager
from queue_manager import QueueManager
from player import MpvPlayer, MpvNotFoundError
import youtube

styles.enable_dpi_awareness()


def format_time(seconds: Optional[float]) -> str:
    """Format seconds into mm:ss or hh:mm:ss string, or --:-- if None."""
    if seconds is None or seconds < 0:
        return "--:--"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def get_base_dir() -> str:
    """Return directory of running executable or script for persistent local config."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_app_config() -> Dict[str, Any]:
    """Read app configuration from config.json with safe defaults."""
    cfg_path = os.path.join(get_base_dir(), "config.json")
    defaults = {
        "youtube_api_key": "",
        "hotkey": "ctrl+shift+p",
        "always_on_top": False
    }
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults


def save_app_config(updates: Dict[str, Any]):
    """Persist updated config values to config.json."""
    cfg_path = os.path.join(get_base_dir(), "config.json")
    current = load_app_config()
    current.update(updates)
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception as e:
        print(f"[Config Save Error] {e}")


class TactileIconButton(tk.Label):
    """Refined tactile hardware button using 4x supersampled vector icons."""

    def __init__(self, parent, icon_type: str, size: int,
                 fg_color: str, hover_fg: str,
                 bg_color: Optional[str] = None, hover_bg: Optional[str] = None,
                 ring_color: Optional[str] = None, ring_width: float = 1.0,
                 command=None, **kwargs):
        super().__init__(parent, bg=bg_color or styles.BG_APP, bd=0, cursor="hand2", **kwargs)
        self.icon_type = icon_type
        self.size = size
        self.fg_color = fg_color
        self.hover_fg = hover_fg
        self.bg_color = bg_color
        self.hover_bg = hover_bg
        self.ring_color = ring_color
        self.ring_width = ring_width
        self.command = command
        self.is_hovered = False

        self._render()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def set_active_state(self, is_active: bool, active_fg: str, active_bg: Optional[str] = None):
        """Toggle active visual state (used for Pin toggle)."""
        if is_active:
            self.fg_color = active_fg
            if active_bg:
                self.bg_color = active_bg
        else:
            self.fg_color = styles.TEXT_MUTED
            if active_bg:
                self.bg_color = styles.BG_SURFACE
        self._render()

    def update_icon(self, icon_type: str, fg_color: Optional[str] = None,
                    bg_color: Optional[str] = None, hover_bg: Optional[str] = None,
                    ring_color: Optional[str] = None):
        self.icon_type = icon_type
        if fg_color:
            self.fg_color = fg_color
        if bg_color:
            self.bg_color = bg_color
        if hover_bg:
            self.hover_bg = hover_bg
        if ring_color:
            self.ring_color = ring_color
        self._render()

    def _render(self):
        fg = self.hover_fg if self.is_hovered else self.fg_color
        bg = self.hover_bg if self.is_hovered else self.bg_color
        self.photo = icons.render_icon(
            self.icon_type,
            size=self.size,
            fg_color=fg,
            bg_color=bg,
            ring_color=self.ring_color,
            ring_width=self.ring_width
        )
        self.configure(image=self.photo)

    def _on_enter(self, event):
        self.is_hovered = True
        self._render()

    def _on_leave(self, event):
        self.is_hovered = False
        self._render()

    def _on_click(self, event):
        if self.command:
            self.command()


class SpectrumVisualizer(tk.Canvas):
    """
    Fluid 12-band stereo graphic spectrum / VU meter display.
    Animates dynamically while audio is streaming with illuminated LED ladder bars.
    """

    def __init__(self, parent, width=128, height=36, bg=styles.BG_SURFACE, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.num_bars = 11
        self.is_active = False

        self.levels = [0.08] * self.num_bars
        self.target_levels = [0.08] * self.num_bars
        self.peaks = [0.10] * self.num_bars

        self.redraw()

    def set_active(self, active: bool):
        self.is_active = active

    def tick(self):
        """Advance animation frame (~24 fps)."""
        if self.is_active:
            for i in range(self.num_bars):
                bias = 0.5 + 0.3 * math.sin(time.time() * 4.0 + i * 0.6)
                r = random.uniform(0.15, 0.95) * bias
                self.target_levels[i] = max(0.12, min(0.98, r))
        else:
            t = time.time() * 2.0
            for i in range(self.num_bars):
                self.target_levels[i] = 0.08 + 0.04 * math.sin(t + i * 0.4)

        for i in range(self.num_bars):
            self.levels[i] += (self.target_levels[i] - self.levels[i]) * 0.35
            if self.levels[i] > self.peaks[i]:
                self.peaks[i] = self.levels[i]
            else:
                self.peaks[i] = max(self.levels[i], self.peaks[i] - 0.02)

        self.redraw()

    def redraw(self):
        self.delete("all")
        pad_x = 4
        avail_w = self.width - 2 * pad_x
        bar_w = int(avail_w / self.num_bars) - 2
        pad_y = 3
        usable_h = self.height - 2 * pad_y

        num_segments = 7
        seg_h = int((usable_h - (num_segments - 1) * 2) / num_segments)

        for i in range(self.num_bars):
            x = pad_x + i * (bar_w + 2)
            lvl = self.levels[i]
            lit_count = int(round(lvl * num_segments))

            for s in range(num_segments):
                y = self.height - pad_y - (s + 1) * (seg_h + 2)
                is_lit = s < lit_count

                if is_lit:
                    if s >= 5:
                        color = styles.ACCENT_CORAL      # Peak Red/Coral
                    elif s >= 3:
                        color = styles.ACCENT_AMBER      # Mid Amber
                    else:
                        color = styles.ACCENT_CYAN       # Low VFD Cyan
                else:
                    color = "#181b26"                    # Inactive unlit block

                self.create_rectangle(
                    x, y, x + bar_w, y + seg_h,
                    fill=color, outline=""
                )

            peak_s = int(min(num_segments - 1, self.peaks[i] * num_segments))
            py = self.height - pad_y - (peak_s + 1) * (seg_h + 2)
            peak_col = styles.ACCENT_AMBER_BRIGHT if peak_s < 5 else styles.ACCENT_CORAL_HOVER
            self.create_line(x, py, x + bar_w, py, fill=peak_col, width=1.5)


class AlbumArtView(tk.Canvas):
    """Clean static thumbnail and album art frame with dark obsidian border."""

    def __init__(self, parent, size=88, bg=styles.BG_DECK_GLASS, **kwargs):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, **kwargs)
        self.size = size
        self.current_photo: Optional[ImageTk.PhotoImage] = None
        self.default_logo: Optional[ImageTk.PhotoImage] = icons.load_app_logo(size - 8)
        self.redraw()

    def set_artwork(self, photo: Optional[ImageTk.PhotoImage]):
        self.current_photo = photo
        self.redraw()

    def redraw(self):
        self.delete("all")
        cx = self.size / 2.0
        cy = self.size / 2.0

        if self.current_photo:
            self.create_image(cx, cy, image=self.current_photo)
        elif self.default_logo:
            self.create_image(cx, cy, image=self.default_logo)
        else:
            pad = 4
            self.create_rectangle(pad, pad, self.size - pad, self.size - pad,
                                  fill="#12141e", outline=styles.BORDER_SUBTLE, width=1)
            r = 16
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             outline=styles.BORDER_MUTED, width=1.5)
            self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                             fill=styles.BORDER_MUTED, outline="")


class TimelineScrubber(tk.Frame):
    """
    Precision VFD fluorescent timeline scrubber.
    Displays digital timecode readouts, glowing cyan progress rail, and interactive thumb.
    """

    def __init__(self, parent, on_seek_callback=None, height=26, bg=styles.BG_APP, **kwargs):
        super().__init__(parent, bg=bg, height=height, **kwargs)
        self.on_seek_callback = on_seek_callback
        self.current_pos = 0.0
        self.duration = 0.0
        self.is_dragging = False
        self.height = height

        self.pack_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        self.lbl_elapsed = tk.Label(
            self,
            text="00:00",
            font=styles.font_time(),
            fg=styles.TEXT_CYAN,
            bg=bg,
            width=6,
            anchor="e"
        )
        self.lbl_elapsed.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.canvas = tk.Canvas(
            self,
            height=height,
            bg=bg,
            highlightthickness=0,
            cursor="hand2"
        )
        self.canvas.grid(row=0, column=1, sticky="ew")

        self.lbl_total = tk.Label(
            self,
            text="--:--",
            font=styles.font_time(),
            fg=styles.TEXT_SUBTLE,
            bg=bg,
            width=6,
            anchor="w"
        )
        self.lbl_total.grid(row=0, column=2, padx=(8, 0), sticky="e")

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    def set_playback_times(self, pos: Optional[float], dur: Optional[float]):
        """Update elapsed and duration times if user is not actively dragging."""
        if self.is_dragging:
            return

        self.duration = dur if (dur and dur > 0) else 0.0
        self.current_pos = pos if (pos and pos >= 0) else 0.0

        if self.duration > 0:
            self.lbl_elapsed.configure(text=format_time(self.current_pos), fg=styles.TEXT_CYAN)
            self.lbl_total.configure(text=format_time(self.duration), fg=styles.TEXT_MUTED)
        else:
            self.lbl_elapsed.configure(text=format_time(self.current_pos) if pos else "00:00",
                                       fg=styles.TEXT_MUTED)
            self.lbl_total.configure(text="--:--", fg=styles.TEXT_SUBTLE)

        self.redraw()

    def redraw(self):
        self.delete = self.canvas.delete
        self.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1:
            return

        pad_x = 6
        cy = h / 2.0
        rail_w = w - 2 * pad_x
        if rail_w <= 0:
            return

        self.canvas.create_line(
            pad_x, cy, w - pad_x, cy,
            fill="#181b26",
            width=5,
            capstyle=tk.ROUND
        )
        self.canvas.create_line(
            pad_x, cy, w - pad_x, cy,
            fill=styles.BORDER_SUBTLE,
            width=3,
            capstyle=tk.ROUND
        )

        if self.duration > 0:
            frac = max(0.0, min(1.0, self.current_pos / self.duration))
            marker_x = pad_x + frac * rail_w

            if marker_x > pad_x:
                self.canvas.create_line(
                    pad_x, cy, marker_x, cy,
                    fill=styles.ACCENT_CYAN,
                    width=3.5,
                    capstyle=tk.ROUND
                )

            r = 5.5
            self.canvas.create_oval(
                marker_x - r, cy - r,
                marker_x + r, cy + r,
                fill=styles.ACCENT_CYAN,
                outline="#ffffff",
                width=1.5
            )

    def _frac_from_event_x(self, x: int) -> float:
        pad_x = 6
        w = self.canvas.winfo_width()
        rail_w = w - 2 * pad_x
        if rail_w <= 0:
            return 0.0
        clamped_x = max(pad_x, min(w - pad_x, x))
        return (clamped_x - pad_x) / float(rail_w)

    def _on_press(self, event):
        if self.duration <= 0:
            return
        self.is_dragging = True
        frac = self._frac_from_event_x(event.x)
        self.current_pos = frac * self.duration
        self.lbl_elapsed.configure(text=format_time(self.current_pos))
        self.redraw()

    def _on_drag(self, event):
        if not self.is_dragging or self.duration <= 0:
            return
        frac = self._frac_from_event_x(event.x)
        self.current_pos = frac * self.duration
        self.lbl_elapsed.configure(text=format_time(self.current_pos))
        self.redraw()

    def _on_release(self, event):
        if not self.is_dragging:
            return
        self.is_dragging = False
        if self.duration > 0:
            frac = self._frac_from_event_x(event.x)
            seek_target = frac * self.duration
            self.current_pos = seek_target
            self.redraw()
            if self.on_seek_callback:
                self.on_seek_callback(seek_target)


class RetroVolumeSlider(tk.Canvas):
    """Analog Hi-Fi volume slider with dual-color level rail and thumb."""

    def __init__(self, parent, initial_vol=100, on_change_callback=None,
                 width=84, height=18, bg=styles.BG_SURFACE, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.volume = max(0, min(100, int(initial_vol)))
        self.on_change = on_change_callback
        self.is_dragging = False

        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.redraw()

    def set_volume(self, val: int):
        self.volume = max(0, min(100, int(val)))
        self.redraw()

    def _calc_vol(self, x: int) -> int:
        pad_x = 6
        usable = self.width - 2 * pad_x
        frac = (x - pad_x) / float(usable)
        return int(round(max(0.0, min(1.0, frac)) * 100))

    def _on_click(self, event):
        self.is_dragging = True
        self.volume = self._calc_vol(event.x)
        self.redraw()
        if self.on_change:
            self.on_change(self.volume)

    def _on_drag(self, event):
        if self.is_dragging:
            self.volume = self._calc_vol(event.x)
            self.redraw()
            if self.on_change:
                self.on_change(self.volume)

    def _on_release(self, event):
        self.is_dragging = False

    def redraw(self):
        self.delete("all")
        pad_x = 6
        cy = self.height / 2.0
        usable = self.width - 2 * pad_x

        self.create_line(pad_x, cy, self.width - pad_x, cy,
                         fill="#181b26", width=4, capstyle=tk.ROUND)

        frac = self.volume / 100.0
        marker_x = pad_x + frac * usable
        if marker_x > pad_x:
            self.create_line(pad_x, cy, marker_x, cy,
                             fill=styles.ACCENT_CYAN, width=3, capstyle=tk.ROUND)

        r = 4.5
        self.create_oval(
            marker_x - r, cy - r,
            marker_x + r, cy + r,
            fill=styles.ACCENT_CYAN,
            outline="#ffffff",
            width=1.0
        )


class QueueOverviewPanel(tk.Frame):
    """Compact scrollable overview of the upcoming playlist queue in the middle section."""

    def __init__(self, parent, on_play_item, on_remove_item, on_clear_queue, bg=styles.BG_DECK_GLASS, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.on_play_item = on_play_item
        self.on_remove_item = on_remove_item
        self.on_clear_queue = on_clear_queue

        self.header_frame = tk.Frame(self, bg=bg)
        self.header_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(6, 4))

        self.title_lbl = tk.Label(
            self.header_frame,
            text="QUEUE",
            font=styles.font_label(),
            fg=styles.TEXT_CYAN,
            bg=bg
        )
        self.title_lbl.pack(side=tk.LEFT)

        self.count_lbl = tk.Label(
            self.header_frame,
            text="(0)",
            font=styles.font_small(),
            fg=styles.TEXT_MUTED,
            bg=bg
        )
        self.count_lbl.pack(side=tk.LEFT, padx=(6, 0))

        self.clear_btn = tk.Button(
            self.header_frame,
            text="Clear",
            font=styles.font_small(),
            fg=styles.TEXT_MUTED,
            bg=bg,
            activeforeground=styles.ERROR_COLOR,
            activebackground=bg,
            bd=0,
            cursor="hand2",
            command=self.on_clear_queue
        )
        self.clear_btn.pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 2), pady=(0, 4))

        self.scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview, width=8)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.list_frame = tk.Frame(self.canvas, bg=bg)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")

        self.list_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.list_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def update_queue(self, items: List[Dict[str, Any]], current_index: int = -1):
        for w in self.list_frame.winfo_children():
            w.destroy()

        count = len(items)
        self.count_lbl.configure(text=f"({count})")
        if count == 0:
            self.clear_btn.pack_forget()
            self.scrollbar.pack_forget()
            empty_lbl = tk.Label(
                self.list_frame,
                text="Queue is empty\nSearch or paste a link to add tracks",
                font=styles.font_small(),
                fg=styles.TEXT_MUTED,
                bg=self["bg"],
                justify=tk.CENTER,
                pady=16
            )
            empty_lbl.pack(fill=tk.BOTH, expand=True)
            empty_lbl.bind("<MouseWheel>", self._on_mousewheel)
            return

        self.clear_btn.pack(side=tk.RIGHT)
        if count > 3:
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 2), pady=(0, 4))
        else:
            self.scrollbar.pack_forget()

        for idx, item in enumerate(items):
            is_current = (idx == current_index)
            row_bg = styles.BG_SURFACE_HOVER if is_current else styles.BG_SURFACE_LIGHT

            row = tk.Frame(self.list_frame, bg=row_bg, bd=1, relief=tk.SOLID, cursor="hand2")
            row.pack(fill=tk.X, pady=2, padx=2)

            if is_current:
                num_text = "▶"
                num_fg = styles.ACCENT_CYAN
            else:
                num_text = f"{idx + 1}."
                num_fg = styles.TEXT_MUTED

            num_lbl = tk.Label(
                row,
                text=num_text,
                font=("Segoe UI", 8, "bold" if is_current else "normal"),
                fg=num_fg,
                bg=row_bg,
                width=3,
                anchor="center" if is_current else "e"
            )
            num_lbl.pack(side=tk.LEFT, padx=(3, 2))

            title = item.get("title", "Untitled")
            display_title = title if len(title) <= 26 else title[:24] + "..."

            t_lbl = tk.Label(
                row,
                text=display_title,
                font=styles.font_small(),
                fg=styles.ACCENT_CYAN if is_current else styles.TEXT_MAIN,
                bg=row_bg,
                anchor="w"
            )
            t_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 4))

            del_btn = tk.Label(
                row,
                text="✕",
                font=("Segoe UI", 8, "bold"),
                fg=styles.TEXT_MUTED,
                bg=row_bg,
                cursor="hand2",
                padx=6,
                pady=1
            )
            del_btn.pack(side=tk.RIGHT, padx=(0, 2))

            def make_click(i):
                return lambda e: self.on_play_item(i)

            def make_del(i):
                def _del_handler(e):
                    self.on_remove_item(i)
                    return "break"
                return _del_handler

            def make_hover(r, n, t, d, h, cur):
                if cur:
                    c = styles.BG_SURFACE_HOVER
                else:
                    c = styles.BG_SURFACE_HOVER if h else styles.BG_SURFACE_LIGHT
                r.configure(bg=c)
                n.configure(bg=c)
                t.configure(bg=c)
                d.configure(bg=c)

            for w in (row, num_lbl, t_lbl):
                w.bind("<Button-1>", make_click(idx))
                w.bind("<Enter>", lambda e, r=row, n=num_lbl, t=t_lbl, d=del_btn, cur=is_current: make_hover(r, n, t, d, True, cur))
                w.bind("<Leave>", lambda e, r=row, n=num_lbl, t=t_lbl, d=del_btn, cur=is_current: make_hover(r, n, t, d, False, cur))
                w.bind("<MouseWheel>", self._on_mousewheel)

            del_btn.bind("<Button-1>", make_del(idx))
            del_btn.bind("<Enter>", lambda e, d=del_btn: d.configure(fg=styles.ERROR_COLOR))
            del_btn.bind("<Leave>", lambda e, d=del_btn: d.configure(fg=styles.TEXT_MUTED))
            del_btn.bind("<MouseWheel>", self._on_mousewheel)


class SearchDropdown(tk.Toplevel):
    """Floating dropdown menu for search results with thumbnail previews and tactile hover."""

    def __init__(self, parent, app, on_select_callback):
        super().__init__(parent)
        self.app = app
        self.on_select_callback = on_select_callback
        self.overrideredirect(True)
        self.configure(bg=styles.BG_APP)
        self.attributes("-topmost", True)
        self.withdraw()

        self.border_frame = tk.Frame(self, bg=styles.BORDER_SUBTLE, bd=1)
        self.border_frame.pack(fill=tk.BOTH, expand=True)

        self.list_container = tk.Frame(self.border_frame, bg=styles.BG_SURFACE)
        self.list_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.thumb_cache = {}

    def display_results(self, x, y, width, results: List[Dict[str, Any]]):
        for widget in self.list_container.winfo_children():
            widget.destroy()

        if not results:
            self.withdraw()
            return

        self.geometry(f"{width}x{min(len(results) * 54 + 4, 330)}+{x}+{y}")

        for item in results:
            row = tk.Frame(self.list_container, bg=styles.BG_SURFACE, cursor="hand2")
            row.pack(fill=tk.X, padx=2, pady=1)

            thumb_frame = tk.Frame(row, bg=styles.BORDER_SUBTLE, bd=1)
            thumb_frame.pack(side=tk.LEFT, padx=(6, 8), pady=4)

            thumb_lbl = tk.Label(thumb_frame, bg=styles.BG_SURFACE_LIGHT, width=6, height=2)
            thumb_lbl.pack()

            info_frame = tk.Frame(row, bg=styles.BG_SURFACE)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=4)

            title = item.get("title", "Untitled")
            if len(title) > 42:
                title = title[:40] + "..."
            tlbl = tk.Label(info_frame, text=title, font=styles.font_body_bold(),
                            fg=styles.TEXT_MAIN, bg=styles.BG_SURFACE, anchor="w")
            tlbl.pack(fill=tk.X)

            channel = item.get("channel", "Unknown Channel")
            clbl = tk.Label(info_frame, text=channel, font=styles.font_small(),
                            fg=styles.TEXT_MUTED, bg=styles.BG_SURFACE, anchor="w")
            clbl.pack(fill=tk.X)

            for w in (row, thumb_frame, thumb_lbl, info_frame, tlbl, clbl):
                w.bind("<Button-1>", lambda e, it=item: self._select_item(it))
                w.bind("<Enter>", lambda e, r=row, inf=info_frame, t=tlbl, c=clbl:
                       self._hover_row(r, inf, t, c, True))
                w.bind("<Leave>", lambda e, r=row, inf=info_frame, t=tlbl, c=clbl:
                       self._hover_row(r, inf, t, c, False))

            if item.get("thumbnail_url"):
                self._load_async_thumb(item["thumbnail_url"], thumb_lbl)

        self.deiconify()
        self.lift()

    def _hover_row(self, row, info_frame, tlbl, clbl, is_hover: bool):
        bg = styles.BG_SURFACE_HOVER if is_hover else styles.BG_SURFACE
        row.configure(bg=bg)
        info_frame.configure(bg=bg)
        tlbl.configure(bg=bg)
        clbl.configure(bg=bg)

    def _select_item(self, item):
        self.withdraw()
        self.on_select_callback(item)

    def _load_async_thumb(self, url: str, label: tk.Label):
        if not url:
            return
        if url in self.thumb_cache:
            label.configure(image=self.thumb_cache[url], width=0, height=0)
            return

        def fetch():
            try:
                res = requests.get(url, timeout=4)
                if res.status_code == 200:
                    img = Image.open(io.BytesIO(res.content))
                    img = img.resize((48, 36), Image.Resampling.LANCZOS)
                    self.app.run_on_ui(self._set_thumb_image, url, label, img)
            except Exception:
                pass

        threading.Thread(target=fetch, daemon=True).start()

    def _set_thumb_image(self, url: str, label: tk.Label, img: Image.Image):
        photo = ImageTk.PhotoImage(img)
        self.thumb_cache[url] = photo
        if label.winfo_exists():
            label.configure(image=photo, width=0, height=0)


class OptionsModal(tk.Toplevel):
    """Sleek retro-modern options dialog for configuring global hotkeys and overlay state."""

    def __init__(self, app: "MediaPlayerApp"):
        super().__init__(app.root)
        self.app = app
        self.overrideredirect(True)
        self.configure(bg=styles.BG_APP)
        self.attributes("-topmost", True)
        self.is_recording = False

        outer_frame = tk.Frame(self, bg=styles.BORDER_SUBTLE, bd=1)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        inner_card = tk.Frame(outer_frame, bg=styles.BG_SURFACE, padx=18, pady=16)
        inner_card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        title_row = tk.Frame(inner_card, bg=styles.BG_SURFACE)
        title_row.pack(fill=tk.X, pady=(0, 12))

        self.modal_logo = icons.load_app_logo(16)
        if self.modal_logo:
            lbl_logo = tk.Label(title_row, image=self.modal_logo, bg=styles.BG_SURFACE)
            lbl_logo.pack(side=tk.LEFT, padx=(0, 6))

        lbl_title = tk.Label(title_row, text="BRAGI SETTINGS",
                             font=styles.font_label(), fg=styles.ACCENT_CYAN, bg=styles.BG_SURFACE)
        lbl_title.pack(side=tk.LEFT)

        btn_close = tk.Label(title_row, text="✕", font=("Segoe UI", 10, "bold"),
                             fg=styles.TEXT_MUTED, bg=styles.BG_SURFACE, cursor="hand2")
        btn_close.pack(side=tk.RIGHT)
        btn_close.bind("<Button-1>", lambda e: self.destroy())

        lbl_hotkey_desc = tk.Label(inner_card, text="GLOBAL OVERLAY HOTKEY",
                                   font=styles.font_label(), fg=styles.TEXT_MUTED, bg=styles.BG_SURFACE)
        lbl_hotkey_desc.pack(anchor="w", pady=(0, 4))

        hotkey_box = tk.Frame(inner_card, bg=styles.BG_SURFACE)
        hotkey_box.pack(fill=tk.X, pady=(0, 6))

        self.hotkey_display = tk.Label(
            hotkey_box,
            text=self.app.current_hotkey.upper(),
            font=styles.font_time(),
            fg=styles.TEXT_CYAN,
            bg=styles.BG_SURFACE_LIGHT,
            bd=1,
            relief=tk.SOLID,
            padx=10,
            pady=5,
            width=18,
            anchor="w"
        )
        self.hotkey_display.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_record = tk.Button(
            hotkey_box,
            text="RECORD KEY",
            font=styles.font_small(),
            bg=styles.ACCENT_CYAN,
            fg="#0a0b10",
            activebackground=styles.ACCENT_CYAN_DIM,
            activeforeground="#ffffff",
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._on_record_clicked
        )
        self.btn_record.pack(side=tk.LEFT)

        self.hotkey_status_lbl = tk.Label(
            inner_card,
            text="Press this hotkey anywhere to show or hide the player.",
            font=styles.font_small(),
            fg=styles.TEXT_SUBTLE,
            bg=styles.BG_SURFACE,
            anchor="w"
        )
        self.hotkey_status_lbl.pack(fill=tk.X, pady=(0, 12))

        self.topmost_var = tk.BooleanVar(value=self.app.always_on_top)
        chk_frame = tk.Frame(inner_card, bg=styles.BG_SURFACE)
        chk_frame.pack(fill=tk.X, pady=(0, 16))

        self.chk_topmost = tk.Checkbutton(
            chk_frame,
            text="Always keep window on top",
            variable=self.topmost_var,
            font=styles.font_body(),
            fg=styles.TEXT_MAIN,
            bg=styles.BG_SURFACE,
            activebackground=styles.BG_SURFACE,
            activeforeground=styles.TEXT_MAIN,
            selectcolor=styles.BG_SURFACE_LIGHT,
            command=self._on_always_on_top_toggled
        )
        self.chk_topmost.pack(anchor="w")

        btn_dismiss = tk.Button(
            inner_card,
            text="SAVE & CLOSE",
            font=styles.font_label(),
            bg=styles.ACCENT_CYAN,
            fg="#0a0b10",
            activebackground=styles.ACCENT_CYAN_DIM,
            activeforeground="#ffffff",
            bd=0,
            padx=16,
            pady=5,
            cursor="hand2",
            command=self.destroy
        )
        btn_dismiss.pack(anchor="e")

        self.update_idletasks()
        w = 380
        h = 230
        px = self.app.root.winfo_x() + (self.app.root.winfo_width() - w) // 2
        py = self.app.root.winfo_y() + (self.app.root.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{px}+{py}")

    def _on_record_clicked(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.btn_record.configure(text="LISTENING...", bg=styles.ACCENT_AMBER)
        self.hotkey_status_lbl.configure(text="Press your desired hotkey combination now...",
                                         fg=styles.ACCENT_CYAN)

        def worker():
            combo = HotkeyManager.record_hotkey()
            self.app.run_on_ui(self._on_hotkey_captured, combo)

        threading.Thread(target=worker, daemon=True).start()

    def _on_hotkey_captured(self, combo: str):
        self.is_recording = False
        self.btn_record.configure(text="RECORD KEY", bg=styles.ACCENT_CYAN)
        if combo:
            success = self.app.update_hotkey(combo)
            if success:
                self.hotkey_display.configure(text=combo.upper())
                self.hotkey_status_lbl.configure(text="Hotkey registered successfully.",
                                                 fg=styles.ACCENT_EMERALD)
            else:
                self.hotkey_status_lbl.configure(text=f"Failed to register '{combo}'. Try another.",
                                                 fg=styles.ERROR_COLOR)
        else:
            self.hotkey_status_lbl.configure(text="Recording cancelled.", fg=styles.TEXT_SUBTLE)

    def _on_always_on_top_toggled(self):
        val = bool(self.topmost_var.get())
        self.app.update_always_on_top(val)


class MediaPlayerApp:
    """Lightweight desktop YouTube background audio player with Retro-Modern Hi-Fi aesthetic."""

    def __init__(self, root: tk.Tk):
        self.root = root
        styles.init_fonts()

        self.config = load_app_config()
        self.current_hotkey = self.config.get("hotkey", "ctrl+shift+p")
        self.always_on_top = bool(self.config.get("always_on_top", False))

        self.root.title("Bragi")
        self.root.overrideredirect(True)
        self.root.resizable(True, True)
        self.win_width = 660
        self.win_height = 410
        self.root.geometry(f"{self.win_width}x{self.win_height}+160+100")
        self.root.minsize(520, 340)
        self.root.maxsize(860, 520)
        self.root.configure(bg=styles.BG_APP)

        self._app_icon_photo = icons.load_app_logo(32)
        if self._app_icon_photo:
            try:
                self.root.iconphoto(True, self._app_icon_photo)
            except Exception:
                pass
        ico_path = os.path.join(get_base_dir(), "icon.ico")
        if os.path.isfile(ico_path):
            try:
                self.root.iconbitmap(default=ico_path)
            except Exception:
                pass

        if self.always_on_top:
            self.root.attributes("-topmost", True)

        self.apply_taskbar_style()

        self.tray_mgr = SystemTrayManager(
            on_restore=lambda: self.run_on_ui(self.restore_from_tray),
            on_quit=lambda: self.run_on_ui(self._on_close)
        )
        self.hotkey_mgr = HotkeyManager(
            callback=lambda: self.run_on_ui(self.toggle_overlay)
        )
        self._register_initial_hotkey()

        self.queue_mgr = QueueManager()
        self.current_track: Optional[Dict[str, Any]] = None
        self.is_resolving_stream = False
        self.thumb_image_cache = {}
        self.cached_banner_photo: Optional[ImageTk.PhotoImage] = None
        self.ambient_idle_banner_photo: Optional[ImageTk.PhotoImage] = None

        self.task_queue = queue.Queue()
        self._process_task_queue()

        self.player: Optional[MpvPlayer] = None
        self._init_player()

        self._drag_start_x = 0
        self._drag_start_y = 0

        self._build_layout()

        self._poll_playback_timeline()

        self._animate_ui_frame()

        self.root.bind("<Button-1>", self._on_window_click)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._update_now_playing_display()
        self._update_queue_display()


    def apply_taskbar_style(self):
        """Force WS_EX_APPWINDOW on Windows for Taskbar and Alt-Tab visibility without DWM repaint conflict."""
        if sys.platform == "win32":
            try:
                self.root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                GWL_EXSTYLE = -20
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_TOOLWINDOW = 0x00000080

                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                new_ex_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex_style)
            except Exception as e:
                print(f"[Win32 Taskbar Style Error] {e}")

    def _start_drag(self, event):
        """Record initial mouse offset using global screen coordinates."""
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        """Fluid, jitter-free dragging tracking absolute cursor position."""
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def _start_resize(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_w = self.root.winfo_width()
        self._resize_start_h = self.root.winfo_height()

    def _on_resize(self, event):
        dx = event.x_root - self._resize_start_x
        dy = event.y_root - self._resize_start_y
        new_w = max(520, min(860, self._resize_start_w + dx))
        new_h = max(340, min(520, self._resize_start_h + dy))
        self.root.geometry(f"{new_w}x{new_h}")

    def minimize_to_tray(self):
        """Withdraw window and activate system tray icon."""
        self.root.withdraw()
        self.tray_mgr.start()

    def restore_from_tray(self):
        """Deiconify window, reapply taskbar style, and restore focus."""
        if hasattr(self, "tray_mgr") and self.tray_mgr:
            self.tray_mgr.stop()
        self.root.deiconify()
        self.root.lift()
        self.apply_taskbar_style()
        if self.always_on_top:
            self.root.attributes("-topmost", True)
        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        self.root.focus_force()

    def toggle_overlay(self):
        """Toggle between hidden/background and visible always-on-top overlay."""
        is_hidden = self.root.state() in ("withdrawn", "iconic")

        is_foreground = False
        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
                is_foreground = (hwnd == fg_hwnd or self.root.winfo_id() == fg_hwnd)
            except Exception:
                is_foreground = False

        if is_hidden or not is_foreground:
            # User wants to OPEN / BRING APP TO FRONT
            self.restore_from_tray()
            self.root.attributes("-topmost", True)
            if sys.platform == "win32":
                try:
                    hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    fg_hwnd = user32.GetForegroundWindow()
                    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
                    cur_tid = kernel32.GetCurrentThreadId()
                    if fg_tid and fg_tid != cur_tid:
                        user32.AttachThreadInput(cur_tid, fg_tid, True)
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.ShowWindow(hwnd, 5)  # SW_SHOW
                        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST
                        user32.SetForegroundWindow(hwnd)
                        user32.BringWindowToTop(hwnd)
                        user32.AttachThreadInput(cur_tid, fg_tid, False)
                    else:
                        user32.ShowWindow(hwnd, 9)
                        user32.ShowWindow(hwnd, 5)
                        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
                        user32.SetForegroundWindow(hwnd)
                        user32.BringWindowToTop(hwnd)
                except Exception:
                    pass
            self.root.focus_force()
        else:
            # Already active in front -> minimize to tray
            self.minimize_to_tray()

    def toggle_pin_on_top(self):
        """Toggle always-on-top pin via title bar button."""
        new_state = not self.always_on_top
        self.update_always_on_top(new_state)

    def _register_initial_hotkey(self):
        if self.current_hotkey:
            self.hotkey_mgr.register(self.current_hotkey)

    def update_hotkey(self, new_hotkey: str) -> bool:
        success = self.hotkey_mgr.register(new_hotkey)
        if success:
            self.current_hotkey = new_hotkey
            save_app_config({"hotkey": new_hotkey})
        return success

    def update_always_on_top(self, enable: bool):
        self.always_on_top = enable
        self.root.attributes("-topmost", enable)
        if hasattr(self, "btn_pin"):
            self.btn_pin.set_active_state(enable, active_fg=styles.ACCENT_CYAN)
        save_app_config({"always_on_top": enable})

    def run_on_ui(self, func, *args):
        """Schedule a function to execute safely on Tkinter's main UI thread."""
        self.task_queue.put((func, args))

    def _process_task_queue(self):
        """Poll task queue and execute pending UI updates on the main thread."""
        try:
            while not self.task_queue.empty():
                try:
                    func, args = self.task_queue.get_nowait()
                    func(*args)
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[UI Queue Error] {e}")
        finally:
            if self.root.winfo_exists():
                self.root.after(25, self._process_task_queue)

    def _init_player(self):
        """Initialize mpv player subprocess and IPC communication."""
        try:
            self.player = MpvPlayer(on_end_of_file=self._on_track_finished)
        except MpvNotFoundError:
            self._show_mpv_missing_dialog()
        except Exception as e:
            messagebox.showerror("mpv Initialization Error", f"Failed to initialize mpv player:\n{e}")

    def _show_mpv_missing_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("mpv Media Engine Required")
        dialog.geometry("540x280")
        dialog.configure(bg=styles.BG_APP)
        dialog.transient(self.root)
        dialog.grab_set()

        outer_card = tk.Frame(dialog, bg=styles.BORDER_SUBTLE, bd=1)
        outer_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        inner_card = tk.Frame(outer_card, bg=styles.BG_SURFACE, padx=20, pady=16)
        inner_card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        title = tk.Label(inner_card, text="MPV ENGINE MISSING",
                         font=styles.font_title(), fg=styles.ERROR_COLOR, bg=styles.BG_SURFACE)
        title.pack(anchor="w", pady=(0, 8))

        msg = "Audio playback requires mpv. Install it via your package manager:"
        tk.Label(inner_card, text=msg, font=styles.font_body(),
                 fg=styles.TEXT_MAIN, bg=styles.BG_SURFACE, justify=tk.LEFT).pack(anchor="w", pady=(0, 10))

        cmd_box = tk.Text(inner_card, height=4, font=("Consolas", 9),
                          bg=styles.BG_SURFACE_LIGHT, fg=styles.TEXT_MAIN, bd=1, relief=tk.SOLID)
        cmd_box.insert(tk.END, "Windows:  winget install mpv-player.mpv-CI.MSVC\n")
        cmd_box.insert(tk.END, "macOS:    brew install mpv\n")
        cmd_box.insert(tk.END, "Linux:    sudo apt install mpv")
        cmd_box.configure(state="disabled")
        cmd_box.pack(fill=tk.X, pady=(0, 12))

        btn_row = tk.Frame(inner_card, bg=styles.BG_SURFACE)
        btn_row.pack(fill=tk.X)

        tk.Button(btn_row, text="Dismiss", command=dialog.destroy,
                  font=styles.font_small(), bg=styles.ACCENT_CYAN, fg="#0a0b10",
                  bd=0, padx=14, pady=4).pack(side=tk.RIGHT)

    def _open_options(self):
        OptionsModal(self)


    def _build_layout(self):
        """Construct clean, compact desktop player layout with illuminated status."""
        self.window_frame = tk.Frame(self.root, bg=styles.BORDER_SUBTLE, bd=1)
        self.window_frame.pack(fill=tk.BOTH, expand=True)

        inner_body = tk.Frame(self.window_frame, bg=styles.BG_APP)
        inner_body.pack(fill=tk.BOTH, expand=True)

        titlebar = tk.Frame(inner_body, bg=styles.BG_SURFACE, height=32)
        titlebar.pack(side=tk.TOP, fill=tk.X)
        titlebar.pack_propagate(False)

        titlebar_line = tk.Frame(inner_body, bg=styles.BORDER_SUBTLE, height=1)
        titlebar_line.pack(side=tk.TOP, fill=tk.X)

        title_box = tk.Frame(titlebar, bg=styles.BG_SURFACE)
        title_box.pack(side=tk.LEFT, padx=(12, 0))

        self.brand_logo_photo = icons.load_app_logo(18)
        if self.brand_logo_photo:
            self.brand_logo_lbl = tk.Label(
                title_box,
                image=self.brand_logo_photo,
                bg=styles.BG_SURFACE
            )
            self.brand_logo_lbl.pack(side=tk.LEFT, padx=(0, 6))
        else:
            self.brand_logo_lbl = None

        title_lbl = tk.Label(
            title_box,
            text="BRAGI",
            font=styles.font_logo(),
            fg=styles.TEXT_MAIN,
            bg=styles.BG_SURFACE
        )
        title_lbl.pack(side=tk.LEFT, padx=(0, 6))

        self.status_led = tk.Label(title_box, text="●", font=("Segoe UI", 8),
                                   fg=styles.ACCENT_EMERALD, bg=styles.BG_SURFACE)
        self.status_led.pack(side=tk.LEFT)

        btn_box = tk.Frame(titlebar, bg=styles.BG_SURFACE)
        btn_box.pack(side=tk.RIGHT, padx=(0, 6))

        self.btn_pin = TactileIconButton(
            btn_box,
            icon_type="pin",
            size=18,
            fg_color=styles.ACCENT_CYAN if self.always_on_top else styles.TEXT_MUTED,
            hover_fg="#ffffff",
            bg_color=styles.BG_SURFACE,
            command=self.toggle_pin_on_top
        )
        self.btn_pin.pack(side=tk.LEFT, padx=2)

        self.btn_gear = TactileIconButton(
            btn_box,
            icon_type="gear",
            size=18,
            fg_color=styles.TEXT_MUTED,
            hover_fg="#ffffff",
            bg_color=styles.BG_SURFACE,
            command=self._open_options
        )
        self.btn_gear.pack(side=tk.LEFT, padx=2)

        self.btn_min = TactileIconButton(
            btn_box,
            icon_type="minimize",
            size=18,
            fg_color=styles.TEXT_MUTED,
            hover_fg="#ffffff",
            bg_color=styles.BG_SURFACE,
            command=self.minimize_to_tray
        )
        self.btn_min.pack(side=tk.LEFT, padx=2)

        self.btn_close = TactileIconButton(
            btn_box,
            icon_type="close",
            size=18,
            fg_color=styles.TEXT_MUTED,
            hover_fg=styles.ERROR_COLOR,
            bg_color=styles.BG_SURFACE,
            command=self._on_close
        )
        self.btn_close.pack(side=tk.LEFT, padx=(2, 2))

        drag_widgets = [titlebar, title_box, self.status_led, title_lbl]
        if self.brand_logo_lbl:
            drag_widgets.append(self.brand_logo_lbl)
        for w in drag_widgets:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        container = tk.Frame(inner_body, bg=styles.BG_APP, padx=12, pady=10)
        container.pack(fill=tk.BOTH, expand=True)

        top_bar_border = tk.Frame(container, bg=styles.BORDER_SUBTLE, bd=1)
        top_bar_border.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        top_bar = tk.Frame(top_bar_border, bg=styles.BG_SURFACE, padx=10, pady=6)
        top_bar.pack(fill=tk.X)
        top_bar.columnconfigure(0, weight=1)
        top_bar.columnconfigure(1, weight=0)
        top_bar.columnconfigure(2, weight=1)

        left_box = tk.Frame(top_bar, bg=styles.BG_SURFACE)
        left_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        lbl_search = tk.Label(left_box, text="SEARCH",
                              font=styles.font_label(), fg=styles.TEXT_CYAN, bg=styles.BG_SURFACE)
        lbl_search.pack(anchor="w", pady=(0, 2))

        search_entry_frame = tk.Frame(left_box, bg=styles.BG_SURFACE_LIGHT, bd=1, relief=tk.SOLID)
        search_entry_frame.pack(fill=tk.X)

        self.search_entry = tk.Entry(
            search_entry_frame,
            font=styles.font_body(),
            bg=styles.BG_SURFACE_LIGHT,
            fg=styles.TEXT_MAIN,
            insertbackground=styles.ACCENT_CYAN,
            bd=0,
            relief=tk.FLAT
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=4)
        self.search_entry.bind("<Return>", lambda e: self._on_search_triggered())

        self.search_btn = tk.Button(
            search_entry_frame,
            text="⌕",
            font=("Segoe UI", 10, "bold"),
            bg=styles.BG_SURFACE_LIGHT,
            fg=styles.ACCENT_CYAN,
            activebackground=styles.BG_SURFACE_HOVER,
            activeforeground="#ffffff",
            bd=0,
            cursor="hand2",
            padx=8,
            command=self._on_search_triggered
        )
        self.search_btn.pack(side=tk.RIGHT)

        self.search_error_lbl = tk.Label(
            left_box,
            text="",
            font=styles.font_small(),
            fg=styles.ERROR_COLOR,
            bg=styles.BG_SURFACE,
            anchor="w",
            wraplength=260,
            justify=tk.LEFT
        )
        self.search_error_lbl.pack(anchor="w", pady=(1, 0))

        self.search_dropdown = SearchDropdown(self.root, app=self, on_select_callback=self._on_search_result_selected)

        divider = tk.Frame(top_bar, bg=styles.BORDER_SUBTLE, width=1)
        divider.grid(row=0, column=1, sticky="ns", padx=6)

        right_box = tk.Frame(top_bar, bg=styles.BG_SURFACE)
        right_box.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        lbl_link = tk.Label(right_box, text="ADD LINK",
                            font=styles.font_label(), fg=styles.TEXT_AMBER, bg=styles.BG_SURFACE)
        lbl_link.pack(anchor="w", pady=(0, 2))

        link_entry_frame = tk.Frame(right_box, bg=styles.BG_SURFACE_LIGHT, bd=1, relief=tk.SOLID)
        link_entry_frame.pack(fill=tk.X)

        self.link_entry = tk.Entry(
            link_entry_frame,
            font=styles.font_body(),
            bg=styles.BG_SURFACE_LIGHT,
            fg=styles.TEXT_MAIN,
            insertbackground=styles.ACCENT_AMBER,
            bd=0,
            relief=tk.FLAT
        )
        self.link_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=4)
        self.link_entry.bind("<Return>", lambda e: self._on_link_entered())

        self.link_btn = tk.Button(
            link_entry_frame,
            text="Load",
            font=styles.font_small(),
            bg=styles.ACCENT_AMBER,
            fg="#0a0b10",
            activebackground=styles.ACCENT_AMBER_BRIGHT,
            activeforeground="#000000",
            bd=0,
            cursor="hand2",
            padx=10,
            command=self._on_link_entered
        )
        self.link_btn.pack(side=tk.RIGHT, padx=2, pady=2)

        self.link_error_lbl = tk.Label(
            right_box,
            text="",
            font=styles.font_small(),
            fg=styles.ERROR_COLOR,
            bg=styles.BG_SURFACE,
            anchor="w",
            wraplength=260,
            justify=tk.LEFT
        )
        self.link_error_lbl.pack(anchor="w", pady=(1, 0))

        bottom_plate_border = tk.Frame(container, bg=styles.BORDER_SUBTLE, bd=1)
        bottom_plate_border.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 0))

        bottom_plate = tk.Frame(bottom_plate_border, bg=styles.BG_SURFACE, padx=12, pady=6)
        bottom_plate.pack(fill=tk.X)

        vol_frame = tk.Frame(bottom_plate, bg=styles.BG_SURFACE)
        vol_frame.pack(side=tk.LEFT, padx=(0, 12))

        vol_icon_lbl = TactileIconButton(
            vol_frame,
            icon_type="volume",
            size=16,
            fg_color=styles.TEXT_MUTED,
            hover_fg="#ffffff",
            bg_color=styles.BG_SURFACE
        )
        vol_icon_lbl.pack(side=tk.LEFT, padx=(0, 4))

        self.vol_slider = RetroVolumeSlider(
            vol_frame,
            initial_vol=100,
            on_change_callback=self._on_volume_changed,
            width=76,
            height=16,
            bg=styles.BG_SURFACE
        )
        self.vol_slider.pack(side=tk.LEFT, padx=(0, 4))

        self.vol_val_lbl = tk.Label(vol_frame, text="100%", font=styles.font_time(),
                                    fg=styles.TEXT_CYAN, bg=styles.BG_SURFACE, width=4)
        self.vol_val_lbl.pack(side=tk.LEFT)

        controls_frame = tk.Frame(bottom_plate, bg=styles.BG_SURFACE)
        controls_frame.pack(side=tk.LEFT, padx=(8, 12))

        self.play_btn = TactileIconButton(
            controls_frame,
            icon_type="play",
            size=40,
            fg_color="#ffffff",
            hover_fg="#ffffff",
            bg_color=styles.ACCENT_CORAL,
            hover_bg=styles.ACCENT_CORAL_HOVER,
            ring_color=styles.ACCENT_CORAL_HOVER,
            ring_width=1.6,
            command=self._on_play_pause_clicked
        )
        self.play_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.skip_btn = TactileIconButton(
            controls_frame,
            icon_type="skip",
            size=30,
            fg_color=styles.TEXT_MAIN,
            hover_fg=styles.ACCENT_CYAN,
            bg_color=styles.BG_SURFACE_LIGHT,
            hover_bg=styles.BG_SURFACE_HOVER,
            ring_color=styles.BORDER_SUBTLE,
            ring_width=1.0,
            command=self._on_skip_clicked
        )
        self.skip_btn.pack(side=tk.LEFT)

        self.resize_grip = tk.Label(
            bottom_plate,
            text="◢",
            font=("Segoe UI", 9),
            fg=styles.TEXT_SUBTLE,
            bg=styles.BG_SURFACE,
            cursor="size_nw_se"
        )
        self.resize_grip.pack(side=tk.RIGHT, padx=(4, 0))
        self.resize_grip.bind("<Button-1>", self._start_resize)
        self.resize_grip.bind("<B1-Motion>", self._on_resize)
        self.resize_grip.bind("<Enter>", lambda e: self.resize_grip.configure(fg=styles.ACCENT_CYAN))
        self.resize_grip.bind("<Leave>", lambda e: self.resize_grip.configure(fg=styles.TEXT_SUBTLE))

        next_frame = tk.Frame(bottom_plate, bg=styles.BG_SURFACE)
        next_frame.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(12, 4))

        lbl_up_next_hdr = tk.Label(next_frame, text="UP NEXT",
                                   font=styles.font_label(), fg=styles.TEXT_AMBER,
                                   bg=styles.BG_SURFACE, anchor="e")
        lbl_up_next_hdr.pack(fill=tk.X, anchor="e")

        self.next_track_lbl = tk.Label(
            next_frame,
            text="None",
            font=styles.font_small(),
            fg=styles.TEXT_MUTED,
            bg=styles.BG_SURFACE,
            anchor="e",
            wraplength=220,
            justify=tk.RIGHT
        )
        self.next_track_lbl.pack(fill=tk.X, anchor="e")

        self.scrubber = TimelineScrubber(
            container,
            on_seek_callback=self._on_seek_requested,
            height=24,
            bg=styles.BG_APP
        )
        self.scrubber.pack(side=tk.BOTTOM, fill=tk.X, pady=(2, 6))

        middle_container = tk.Frame(container, bg=styles.BG_APP)
        middle_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 6))
        middle_container.columnconfigure(0, weight=6)
        middle_container.columnconfigure(1, weight=5)
        middle_container.rowconfigure(0, weight=1)

        np_outer = tk.Frame(middle_container, bg=styles.BORDER_SUBTLE, bd=1)
        np_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        np_inner = tk.Frame(np_outer, bg=styles.BG_DECK_GLASS, padx=10, pady=8)
        np_inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        art_border = tk.Frame(np_inner, bg=styles.BORDER_SUBTLE, bd=1)
        art_border.pack(side=tk.LEFT, padx=(0, 10))

        self.art_canvas = AlbumArtView(art_border, size=88, bg=styles.BG_DECK_GLASS)
        self.art_canvas.pack(padx=1, pady=1)

        plaque_container = tk.Frame(np_inner, bg=styles.BG_DECK_GLASS)
        plaque_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        plaque_top_row = tk.Frame(plaque_container, bg=styles.BG_DECK_GLASS)
        plaque_top_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))

        self.status_badge_lbl = tk.Label(
            plaque_top_row,
            text="Ready",
            font=styles.font_small(),
            fg=styles.TEXT_MUTED,
            bg=styles.BG_DECK_GLASS
        )
        self.status_badge_lbl.pack(side=tk.LEFT)

        self.spectrum = SpectrumVisualizer(plaque_top_row, width=80, height=20, bg=styles.BG_DECK_GLASS)
        self.spectrum.pack(side=tk.RIGHT)

        self.plaque_canvas = tk.Canvas(plaque_container, bg=styles.BG_DECK_GLASS, highlightthickness=0)
        self.plaque_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.plaque_canvas.bind("<Configure>", lambda e: self._render_plaque_canvas())

        queue_outer = tk.Frame(middle_container, bg=styles.BORDER_SUBTLE, bd=1)
        queue_outer.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        self.queue_overview = QueueOverviewPanel(
            queue_outer,
            on_play_item=self._play_queue_index,
            on_remove_item=self._remove_queue_index,
            on_clear_queue=self._clear_queue,
            bg=styles.BG_DECK_GLASS
        )
        self.queue_overview.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)


    def _animate_ui_frame(self):
        """Continuously update animated VU visualizer bars."""
        try:
            is_active = bool(self.player and self.player.is_playing() and not self.player.is_paused())
            self.spectrum.set_active(is_active)
            self.spectrum.tick()
        except Exception:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(42, self._animate_ui_frame)

    def _create_ambient_idle_banner(self, width: int = 900, height: int = 200) -> ImageTk.PhotoImage:
        """Generate an ambient dark studio banner with scanlines for idle state."""
        width = max(width, 900)
        height = max(height, 200)
        img = Image.new("RGBA", (width, height), (12, 14, 23, 255))
        draw = ImageDraw.Draw(img)

        for x in range(width):
            t = x / float(width)
            r = int(10 * (1 - t) + 20 * t)
            g = int(14 * (1 - t) + 24 * t)
            b = int(24 * (1 - t) + 42 * t)
            draw.line([(x, 0), (x, height)], fill=(r, g, b, 255))

        for y in range(0, height, 4):
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, 50))

        orb = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        orb_draw = ImageDraw.Draw(orb)
        orb_draw.ellipse([width - 160, -30, width + 50, height + 50], fill=(0, 240, 255, 25))
        orb_blurred = orb.filter(ImageFilter.GaussianBlur(radius=25))
        composite = Image.alpha_composite(img, orb_blurred)

        return ImageTk.PhotoImage(composite)

    def _render_plaque_canvas(self):
        """Render the plaque canvas with blurred banner background and clean typography."""
        self.plaque_canvas.delete("all")
        w = self.plaque_canvas.winfo_width()
        h = self.plaque_canvas.winfo_height()
        if w <= 1:
            w, h = 320, 80

        if self.cached_banner_photo:
            self.plaque_canvas.create_image(0, 0, image=self.cached_banner_photo, anchor="nw")
        else:
            if not self.ambient_idle_banner_photo:
                self.ambient_idle_banner_photo = self._create_ambient_idle_banner(900, 200)
            self.plaque_canvas.create_image(0, 0, image=self.ambient_idle_banner_photo, anchor="nw")

        if not self.current_track:
            status_text = "Ready"
            status_col = styles.TEXT_MUTED
            title_text = "Nothing playing"
            channel_text = "Search or paste a YouTube link to begin."
        else:
            title_text = self.current_track.get("title", "Untitled")
            channel_text = self.current_track.get("channel", "")
            if self.is_resolving_stream:
                status_text = "● Loading..."
                status_col = styles.ACCENT_CYAN
            elif self.player and self.player.is_paused():
                status_text = "● Paused"
                status_col = styles.ACCENT_AMBER
            elif self.player and self.player.is_playing():
                status_text = "● Playing"
                status_col = styles.ACCENT_EMERALD
            else:
                status_text = "Ready"
                status_col = styles.TEXT_MUTED

        self.status_badge_lbl.configure(text=status_text, fg=status_col)

        avail_chars = max(18, int(w / 11.0))
        display_title = title_text if len(title_text) <= avail_chars else title_text[:avail_chars - 3] + "..."

        self.plaque_canvas.create_text(
            10, 24,
            text=display_title,
            font=styles.font_body_bold(),
            fill=styles.TEXT_MAIN,
            anchor="w"
        )

        display_channel = channel_text if len(channel_text) <= avail_chars + 4 else channel_text[:avail_chars + 1] + "..."
        self.plaque_canvas.create_text(
            10, 48,
            text=display_channel,
            font=styles.font_small(),
            fill=styles.TEXT_MUTED,
            anchor="w"
        )

    def _update_now_playing_display(self):
        """Update play/pause button state and refresh the plaque canvas."""
        is_playing = self.player and self.player.is_playing() and not self.player.is_paused()
        if is_playing:
            self.play_btn.update_icon(
                "pause",
                fg_color="#ffffff",
                bg_color=styles.ACCENT_CORAL,
                hover_bg=styles.ACCENT_CORAL_HOVER,
                ring_color=styles.ACCENT_CORAL_HOVER
            )
            self.status_led.configure(fg=styles.ACCENT_CORAL)
        else:
            self.play_btn.update_icon(
                "play",
                fg_color="#ffffff",
                bg_color=styles.ACCENT_CORAL,
                hover_bg=styles.ACCENT_CORAL_HOVER,
                ring_color=styles.ACCENT_CORAL_HOVER
            )
            self.status_led.configure(fg=styles.ACCENT_EMERALD)
        self._render_plaque_canvas()

    def _load_album_art_and_banner(self, url: str):
        """Fetch thumbnail once per track change, produce square art and blurred scanline banner."""
        if not url:
            self.cached_banner_photo = None
            self.art_canvas.set_artwork(None)
            self._render_plaque_canvas()
            return

        if url in self.thumb_image_cache:
            square_photo, banner_photo = self.thumb_image_cache[url]
            self.art_canvas.set_artwork(square_photo)
            self.cached_banner_photo = banner_photo
            self._render_plaque_canvas()
            return

        def worker():
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    raw_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

                    w, h = raw_img.size
                    min_dim = min(w, h)
                    left = (w - min_dim) / 2
                    top = (h - min_dim) / 2
                    img_square = raw_img.crop((left, top, left + min_dim, top + min_dim))
                    img_resized = img_square.resize((88, 88), Image.Resampling.LANCZOS)

                    banner_w, banner_h = 640, 160
                    banner_crop = raw_img.resize((banner_w, banner_h), Image.Resampling.LANCZOS)
                    banner_blurred = banner_crop.filter(ImageFilter.GaussianBlur(radius=20))

                    scrim = Image.new("RGBA", (banner_w, banner_h), (10, 11, 18, 205))
                    composite = Image.alpha_composite(banner_blurred, scrim)

                    draw = ImageDraw.Draw(composite)
                    for y in range(0, banner_h, 4):
                        draw.line([(0, y), (banner_w, y)], fill=(0, 0, 0, 50))

                    self.run_on_ui(self._apply_artwork, url, img_resized, composite)
            except Exception as e:
                print(f"[Art Error] {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _apply_artwork(self, url: str, square_img: Image.Image, banner_img: Image.Image):
        square_photo = ImageTk.PhotoImage(square_img)
        banner_photo = ImageTk.PhotoImage(banner_img)
        self.thumb_image_cache[url] = (square_photo, banner_photo)
        if self.current_track and self.current_track.get("thumbnail_url") == url:
            self.art_canvas.set_artwork(square_photo)
            self.cached_banner_photo = banner_photo
            self._render_plaque_canvas()

    def _play_queue_index(self, index: int):
        """Play selected queue track without removing it from the queue list."""
        track = self.queue_mgr.play_index(index)
        if track:
            self._play_track(track)
            self._update_queue_display()

    def _remove_queue_index(self, index: int):
        """Explicitly remove track from queue when user clicks the X button."""
        self.queue_mgr.remove_at(index)
        self._update_queue_display()

    def _clear_queue(self):
        self.queue_mgr.clear()
        self._update_queue_display()

    def _update_queue_display(self):
        items = self.queue_mgr.get_items()
        curr_idx = self.queue_mgr.get_current_index()
        if hasattr(self, "queue_overview") and self.queue_overview:
            self.queue_overview.update_queue(items, current_index=curr_idx)

        next_track = self.queue_mgr.peek_next()
        if next_track:
            title = next_track.get("title", "")
            if len(title) > 28:
                title = title[:26] + "..."
            remaining = self.queue_mgr.remaining_after_next()
            suffix = f" (+{remaining})" if remaining > 0 else ""
            self.next_track_lbl.configure(text=f'"{title}"{suffix}', fg=styles.TEXT_MAIN)
        else:
            self.next_track_lbl.configure(text="None", fg=styles.TEXT_MUTED)


    def _poll_playback_timeline(self):
        """Poll mpv time-pos and duration every 500ms via IPC from main loop."""
        try:
            if self.player and self.player.has_file_loaded() and not self.is_resolving_stream:
                pos = self.player.get_position()
                dur = self.player.get_duration()
                self.scrubber.set_playback_times(pos, dur)
            else:
                self.scrubber.set_playback_times(None, None)
        except Exception:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(500, self._poll_playback_timeline)

    def _on_seek_requested(self, target_seconds: float):
        if self.player and self.player.has_file_loaded():
            self.player.seek_to(target_seconds)


    def _on_search_triggered(self):
        query = self.search_entry.get().strip()
        self.search_error_lbl.configure(text="")
        if not query:
            return

        self.search_btn.configure(text="⏳")

        def worker():
            try:
                results = youtube.search_videos(query, max_results=6)
                self.run_on_ui(self._on_search_success, results)
            except youtube.MissingApiKeyError as e:
                self.run_on_ui(self._on_search_error, str(e))
            except youtube.InvalidApiKeyError as e:
                self.run_on_ui(self._on_search_error, str(e))
            except Exception as e:
                self.run_on_ui(self._on_search_error, f"Search failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_success(self, results: List[Dict[str, Any]]):
        self.search_btn.configure(text="⌕")
        if not results:
            self.search_error_lbl.configure(text="No tracks found for this title.")
            return

        x = self.search_entry.winfo_rootx() - 8
        y = self.search_entry.winfo_rooty() + self.search_entry.winfo_height() + 8
        width = self.search_entry.winfo_width() + 38
        self.search_dropdown.display_results(x, y, width, results)

    def _on_search_error(self, message: str):
        self.search_btn.configure(text="⌕")
        self.search_error_lbl.configure(text=message)

    def _on_search_result_selected(self, item: Dict[str, Any]):
        self.search_dropdown.withdraw()
        self.search_entry.delete(0, tk.END)
        self.search_error_lbl.configure(text="")

        is_busy = (self.current_track is not None) or self.is_resolving_stream
        self.queue_mgr.add(item)
        self._update_queue_display()
        if not is_busy:
            self._play_queue_index(self.queue_mgr.size() - 1)
        else:
            title = item.get("title", "Track")
            display_title = title if len(title) <= 24 else title[:22] + "..."
            self.search_error_lbl.configure(text=f'Added "{display_title}" to queue', fg=styles.TEXT_CYAN)
            self.root.after(3500, lambda: self.search_error_lbl.configure(text="", fg=styles.ERROR_COLOR))

    def _on_link_entered(self):
        url = self.link_entry.get().strip()
        self.link_error_lbl.configure(text="", fg=styles.ERROR_COLOR)
        if not url:
            return

        self.link_btn.configure(text="Loading...")

        def worker():
            try:
                item = youtube.fetch_oembed(url)
                self.run_on_ui(self._on_link_success, item)
            except Exception as e:
                self.run_on_ui(self._on_link_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_link_success(self, item: Dict[str, Any]):
        self.link_btn.configure(text="Load")
        self.link_entry.delete(0, tk.END)
        self.link_error_lbl.configure(text="")

        is_busy = (self.current_track is not None) or self.is_resolving_stream
        self.queue_mgr.add(item)
        self._update_queue_display()
        if not is_busy:
            self._play_queue_index(self.queue_mgr.size() - 1)
        else:
            title = item.get("title", "Track")
            display_title = title if len(title) <= 24 else title[:22] + "..."
            self.link_error_lbl.configure(text=f'Added "{display_title}" to queue', fg=styles.TEXT_AMBER)
            self.root.after(3500, lambda: self.link_error_lbl.configure(text="", fg=styles.ERROR_COLOR))

    def _on_link_error(self, message: str):
        self.link_btn.configure(text="Load")
        self.link_error_lbl.configure(text=message, fg=styles.ERROR_COLOR)

    def _play_track(self, track: Dict[str, Any]):
        """Immediately switch to and stream the given track."""
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass

        self.current_track = track
        self.is_resolving_stream = True

        self._update_now_playing_display()
        self._update_queue_display()
        self._load_album_art_and_banner(track.get("thumbnail_url"))

        target_url = (
            track.get("webpage_url")
            or (f"https://www.youtube.com/watch?v={track.get('video_id')}" if track.get("video_id") else None)
            or track.get("title")
        )

        def worker():
            try:
                stream_url = youtube.resolve_audio_stream(target_url)
                self.run_on_ui(self._start_stream_playback, stream_url)
            except Exception as e:
                self.run_on_ui(self._on_stream_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _play_next_in_queue(self):
        track = self.queue_mgr.get_next_track()
        if track:
            self._play_track(track)
            self._update_queue_display()
        else:
            self.current_track = None
            self._update_now_playing_display()
            self._update_queue_display()
            self._load_album_art_and_banner(None)

    def _start_stream_playback(self, stream_url: str):
        self.is_resolving_stream = False
        if not self.player:
            self._init_player()
            if not self.player:
                return

        try:
            self.player.load(stream_url)
        except Exception as e:
            print(f"[Playback Load Error] {e}")
            self._on_stream_error(str(e))
            return
        self._update_now_playing_display()

    def _on_stream_error(self, error_message: str):
        self.is_resolving_stream = False
        print(f"[Stream Error] {error_message}")
        self.search_error_lbl.configure(text=f"Stream error: {error_message[:45]}")
        self._update_now_playing_display()
        self._play_next_in_queue()

    def _on_track_finished(self):
        self.run_on_ui(self._play_next_in_queue)

    def skip_to_next(self):
        if self.player:
            self.player.stop()
        self._play_next_in_queue()

    def _on_window_click(self, event):
        if hasattr(self, "search_dropdown") and self.search_dropdown.winfo_viewable():
            widget = event.widget
            if (widget != self.search_entry and widget != self.search_btn and
                not str(widget).startswith(str(self.search_dropdown))):
                self.search_dropdown.withdraw()

    def _on_play_pause_clicked(self):
        if not self.player:
            return

        if not self.player.has_file_loaded():
            if not self.queue_mgr.is_empty() and not self.is_resolving_stream:
                curr_idx = self.queue_mgr.get_current_index()
                if curr_idx == -1:
                    self._play_queue_index(0)
                else:
                    self._play_queue_index(curr_idx)
            return

        if self.is_resolving_stream:
            return

        self.player.toggle_pause()
        self.root.after(60, self._update_now_playing_display)

    def _on_skip_clicked(self):
        self.skip_to_next()

    def _on_volume_changed(self, value: int):
        self.vol_val_lbl.configure(text=f"{value}%")
        if self.player:
            self.player.set_volume(value)

    def _on_close(self):
        """Clean teardown: stop player, tray icon, hotkeys, and destroy window."""
        if self.hotkey_mgr:
            try:
                self.hotkey_mgr.unregister()
            except Exception:
                pass

        if self.tray_mgr:
            try:
                self.tray_mgr.stop()
            except Exception:
                pass

        if self.player:
            try:
                self.player.shutdown()
            except Exception:
                pass

        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = MediaPlayerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
