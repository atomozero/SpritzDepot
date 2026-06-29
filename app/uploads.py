"""Image uploads (icons, screenshots).

A convenience layer: authors may upload an image instead of hosting it
themselves. The cichéto still points at it by URL (served from spritz), so the
git + cache model is untouched. Kept deliberately strict:

  - Only real images (PNG / JPEG / WebP / GIF), detected by magic bytes, not by
    the filename extension. A renamed executable is rejected.
  - Per-kind size caps (config.MAX_ICON_BYTES / MAX_SCREENSHOT_BYTES).
  - Stored under a content-addressed name (sha256 of the bytes), so the path is
    safe by construction (no traversal) and identical uploads dedup.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config


class UploadError(ValueError):
    """An upload that is rejected (wrong type, too big, empty)."""


# (extension, content-type) keyed by the leading magic bytes.
def _sniff(data: bytes) -> tuple[str, str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise UploadError("unsupported image type (allowed: PNG, JPEG, WebP, GIF)")


def content_type_for(filename: str) -> str:
    """Content-type to serve a stored asset with, from its extension."""
    ext = filename.rsplit(".", 1)[-1].lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp"}.get(ext, "application/octet-stream")


def save_image(data: bytes, max_bytes: int) -> str:
    """Validate and store an image, return its served filename.

    Raises UploadError on empty input, an oversize file, or a non-image.
    """
    if not data:
        raise UploadError("empty upload")
    if len(data) > max_bytes:
        raise UploadError(f"image too large ({len(data)} bytes > {max_bytes})")

    ext, _ctype = _sniff(data)  # raises if not a recognized image
    digest = hashlib.sha256(data).hexdigest()
    filename = f"{digest}.{ext}"

    dest_dir = Path(config.UPLOAD_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.exists():  # content-addressed: identical bytes dedup
        dest.write_bytes(data)
    return filename


def asset_path(filename: str) -> Path:
    """Resolve a served filename to its path, guarding against traversal."""
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise UploadError("bad asset filename")
    return Path(config.UPLOAD_DIR) / filename
