"""Small but genuine media files for tests (uploads are decoded, so fake bytes are rejected)."""
from __future__ import annotations

import io

from PIL import Image


def image_bytes(width: int = 800, height: int = 800, fmt: str = "JPEG", color: str = "purple") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, fmt)
    return buffer.getvalue()


def jpeg(width: int = 800, height: int = 800) -> bytes:
    return image_bytes(width, height, "JPEG")


def png(width: int = 800, height: int = 800) -> bytes:
    return image_bytes(width, height, "PNG")


def mp4() -> bytes:
    """The start of an MP4 file: enough for the container check (not a playable video)."""
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
