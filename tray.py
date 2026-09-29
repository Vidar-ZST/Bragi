"""
System tray integration using pystray with a runtime-generated Pillow icon.
Provides background minimization, tray restoration, and application exit.
"""

import os
import sys
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def create_tray_image(size: int = 64) -> Image.Image:
    """Load the official Bragi emblem for the system tray, with high-fidelity scaling."""
    icon_path = os.path.join(get_base_dir(), "icon.png")
    if os.path.isfile(icon_path):
        try:
            img = Image.open(icon_path).convert("RGBA")
            return img.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 3
    draw.ellipse((pad, pad, size - pad, size - pad), fill="#0a0b10", outline="#00f0ff", width=3)
    cx, cy = size / 2.0, size / 2.0
    r = size * 0.22
    points = [(cx - r * 0.65, cy - r * 0.92), (cx + r * 1.05, cy), (cx - r * 0.65, cy + r * 0.92)]
    draw.polygon(points, fill="#ff3366")
    return img


class SystemTrayManager:
    """Manages the lifecycle of the system tray icon."""

    def __init__(self, on_restore: Callable[[], None], on_quit: Callable[[], None]):
        self.on_restore = on_restore
        self.on_quit = on_quit
        self.icon: Optional[pystray.Icon] = None
        self._is_running = False

    def start(self):
        """Initialize and display the system tray icon."""
        if self._is_running and self.icon:
            return

        image = create_tray_image(64)
        menu = pystray.Menu(
            pystray.MenuItem("Open Bragi", lambda icon, item: self._handle_restore(), default=True),
            pystray.MenuItem("Quit", lambda icon, item: self._handle_quit())
        )

        self.icon = pystray.Icon(
            "Bragi",
            image,
            "Bragi - Audio Player",
            menu=menu
        )
        self._is_running = True
        self.icon.run_detached()

    def _handle_restore(self):
        if self.on_restore:
            self.on_restore()

    def _handle_quit(self):
        self.stop()
        if self.on_quit:
            self.on_quit()

    def stop(self):
        """Stop and remove the system tray icon."""
        self._is_running = False
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    def is_running(self) -> bool:
        return self._is_running
