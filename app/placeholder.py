"""Generate a Haiku-flavoured SVG placeholder for apps without an icon.

A stylised leaf shape (evoking Haiku's leaf, not the exact logo) in the
project's green, with the app's initial on top. The background tint is derived
from the name so different apps get distinct-but-coherent shades. SVG keeps it
crisp at any size and is cheap to cache; WebPositive renders basic SVG.
"""
from __future__ import annotations

import hashlib

# Haiku-ish greens to pick from, by a stable hash of the name.
_GREENS = ["#4a9d4e", "#58b35a", "#3f8f54", "#5bb87a", "#479e6b", "#6aa84f"]


def _tint(name: str) -> str:
    h = hashlib.sha256(name.encode("utf-8")).digest()[0]
    return _GREENS[h % len(_GREENS)]


def _initial(name: str) -> str:
    for ch in name:
        if ch.isalnum():
            return ch.upper()
    return "?"


def placeholder_svg(name: str, size: int = 64) -> str:
    """Return an SVG document (string) for `name` at `size` px."""
    bg = _tint(name)
    initial = _initial(name)
    # A simple two-lobe leaf with a central vein, drawn in a 64x64 viewBox and
    # scaled by the SVG viewport. The initial sits in the lower half.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{bg}"/>
      <stop offset="1" stop-color="#2f6b3a"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="64" height="64" rx="14" fill="url(#g)"/>
  <!-- stylised leaf -->
  <path d="M32 9 C20 18 17 31 22 42 C26 35 30 31 32 30 C34 31 38 35 42 42 C47 31 44 18 32 9 Z"
        fill="#ffffff" fill-opacity="0.22"/>
  <path d="M32 12 L32 40" stroke="#ffffff" stroke-opacity="0.30" stroke-width="2" stroke-linecap="round"/>
  <text x="32" y="52" text-anchor="middle" font-family="DejaVu Sans, Verdana, sans-serif"
        font-size="22" font-weight="bold" fill="#ffffff">{initial}</text>
</svg>'''
