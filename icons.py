"""
Pillow-based anti-aliased icon rendering with 4x supersampling and LANCZOS downsampling.
Renders crisp retro-modern studio vector icons for high-DPI displays.
"""

from typing import Optional, Dict, Tuple
from PIL import Image, ImageDraw, ImageTk
import math

import os
import sys

_ICON_CACHE: Dict[Tuple, ImageTk.PhotoImage] = {}


def load_app_logo(size: int = 24) -> Optional[ImageTk.PhotoImage]:
    """Load and downsample the official Bragi lyre emblem with high-fidelity LANCZOS anti-aliasing."""
    cache_key = ("bragi_logo", size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "icon.png")
    if os.path.isfile(icon_path):
        try:
            img = Image.open(icon_path).convert("RGBA")
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            _ICON_CACHE[cache_key] = photo
            return photo
        except Exception:
            pass
    return None


def render_icon(
    icon_type: str,
    size: int,
    fg_color: str,
    bg_color: Optional[str] = None,
    ring_color: Optional[str] = None,
    ring_width: float = 1.0,
    scale: int = 4
) -> ImageTk.PhotoImage:
    """
    Renders an icon at 4x resolution on an RGBA canvas, then downsamples using
    Image.Resampling.LANCZOS to produce razor-sharp, anti-aliased vector graphics.
    """
    cache_key = (icon_type, size, fg_color, bg_color, ring_color, ring_width, scale)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    hi_size = size * scale
    img = Image.new("RGBA", (hi_size, hi_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = hi_size / 2.0
    cy = hi_size / 2.0
    pad = int(1.5 * scale)

    if bg_color or ring_color:
        outline_w = int(max(1, round(ring_width * scale))) if ring_color else 0
        draw.ellipse(
            (pad, pad, hi_size - pad, hi_size - pad),
            fill=bg_color or (0, 0, 0, 0),
            outline=ring_color or None,
            width=outline_w
        )

    if icon_type == "play":
        r = hi_size * 0.22
        offset_x = hi_size * 0.04
        points = [
            (cx - r * 0.65 + offset_x, cy - r * 0.92),
            (cx + r * 1.05 + offset_x, cy),
            (cx - r * 0.65 + offset_x, cy + r * 0.92)
        ]
        draw.polygon(points, fill=fg_color)

    elif icon_type == "pause":
        bar_w = max(2, int(hi_size * 0.09))
        bar_h = hi_size * 0.40
        gap = hi_size * 0.08
        draw.rectangle([cx - gap - bar_w, cy - bar_h/2, cx - gap, cy + bar_h/2], fill=fg_color)
        draw.rectangle([cx + gap, cy - bar_h/2, cx + gap + bar_w, cy + bar_h/2], fill=fg_color)

    elif icon_type == "skip":
        r = hi_size * 0.18
        bar_w = max(2, int(1.8 * scale))
        bar_h = hi_size * 0.36
        points = [
            (cx - r * 0.9, cy - r),
            (cx + r * 0.25, cy),
            (cx - r * 0.9, cy + r)
        ]
        draw.polygon(points, fill=fg_color)
        draw.rectangle([cx + r * 0.45, cy - bar_h/2, cx + r * 0.45 + bar_w, cy + bar_h/2], fill=fg_color)

    elif icon_type == "minimize":
        w = hi_size * 0.44
        line_w = max(2, int(1.6 * scale))
        draw.rectangle([cx - w/2, cy - line_w/2, cx + w/2, cy + line_w/2], fill=fg_color)

    elif icon_type == "close":
        r = hi_size * 0.20
        line_w = max(2, int(1.8 * scale))
        draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=fg_color, width=line_w)
        draw.line([(cx - r, cy + r), (cx + r, cy - r)], fill=fg_color, width=line_w)

    elif icon_type == "gear":
        outer_r = hi_size * 0.32
        inner_r = hi_size * 0.22
        hole_r = hi_size * 0.10
        num_teeth = 8
        for i in range(num_teeth):
            angle = i * (2 * math.pi / num_teeth)
            tx = cx + math.cos(angle) * outer_r
            ty = cy + math.sin(angle) * outer_r
            tooth_w = max(2, int(2.4 * scale))
            draw.line([(cx, cy), (tx, ty)], fill=fg_color, width=tooth_w)

        ring_w = max(2, int(2.2 * scale))
        draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
                     outline=fg_color, width=ring_w)
        draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r],
                     fill=bg_color or (0, 0, 0, 0), outline=fg_color, width=max(1, int(1 * scale)))

    elif icon_type == "pin":
        line_w = max(2, int(1.6 * scale))
        head_r = hi_size * 0.16
        draw.ellipse([cx - head_r, cy - hi_size * 0.35, cx + head_r, cy - hi_size * 0.05],
                     fill=fg_color)
        draw.line([(cx, cy - hi_size * 0.05), (cx, cy + hi_size * 0.32)],
                  fill=fg_color, width=line_w)

    elif icon_type == "search":
        r = hi_size * 0.20
        line_w = max(2, int(1.8 * scale))
        glass_cx = cx - hi_size * 0.06
        glass_cy = cy - hi_size * 0.06
        draw.ellipse([glass_cx - r, glass_cy - r, glass_cx + r, glass_cy + r],
                     outline=fg_color, width=line_w)
        handle_len = hi_size * 0.18
        draw.line([(glass_cx + r * 0.7, glass_cy + r * 0.7),
                   (glass_cx + r * 0.7 + handle_len, glass_cy + r * 0.7 + handle_len)],
                  fill=fg_color, width=line_w)

    elif icon_type == "volume":
        line_w = max(2, int(1.6 * scale))
        speaker_pts = [
            (cx - hi_size * 0.28, cy - hi_size * 0.14),
            (cx - hi_size * 0.10, cy - hi_size * 0.14),
            (cx + hi_size * 0.10, cy - hi_size * 0.28),
            (cx + hi_size * 0.10, cy + hi_size * 0.28),
            (cx - hi_size * 0.10, cy + hi_size * 0.14),
            (cx - hi_size * 0.28, cy + hi_size * 0.14)
        ]
        draw.polygon(speaker_pts, fill=fg_color)
        arc_box = [cx - hi_size * 0.08, cy - hi_size * 0.22, cx + hi_size * 0.28, cy + hi_size * 0.22]
        draw.arc(arc_box, start=-45, end=45, fill=fg_color, width=line_w)

    downsampled = img.resize((size, size), Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(downsampled)
    _ICON_CACHE[cache_key] = photo
    return photo
