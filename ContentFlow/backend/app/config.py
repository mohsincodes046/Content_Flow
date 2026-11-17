from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


def load_backend_environment(env_file: Path | None = None) -> None:
    load_dotenv(
        dotenv_path=env_file or Path(__file__).resolve().parent.parent / ".env",
        override=False,
    )


load_backend_environment()

Platform = Literal["instagram", "facebook", "linkedin", "youtube", "tiktok"]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
SESSION_LIFETIME = timedelta(days=7)
SESSION_COOKIE = "content_flow_session"
ALLOWED_MEDIA_TYPES = ("image/", "video/")

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("CONTENT_FLOW_DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "content_flow.sqlite3"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CONTENT_FLOW_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

def public_api_url() -> str:
    return os.environ.get("CONTENT_FLOW_API_PUBLIC_URL", os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8000")).rstrip("/")


def public_frontend_url() -> str:
    return os.environ.get("CONTENT_FLOW_FRONTEND_URL", "http://localhost:3000").rstrip("/")


_DEV_HOST_MARKERS = ("localhost", "127.0.0.1", "ngrok")


def deployment_warnings() -> list[str]:
    """Settings that work locally but break a hosted deployment (no secrets in the text).
    Only checked on a host (Render, Koyeb or CONTENT_FLOW_COOKIE_SECURE=true)."""
    hosted = any(os.environ.get(k) for k in ("RENDER", "KOYEB_APP_NAME", "KOYEB_SERVICE_NAME")) or \
        os.environ.get("CONTENT_FLOW_COOKIE_SECURE", "").lower() == "true"
    if not hosted:
        return []
    warnings = []
    for name, value in (("CONTENT_FLOW_API_PUBLIC_URL", public_api_url()),
                        ("CONTENT_FLOW_FRONTEND_URL", public_frontend_url()),
                        ("CONTENT_FLOW_ALLOWED_ORIGINS", ",".join(ALLOWED_ORIGINS))):
        if any(marker in value for marker in _DEV_HOST_MARKERS) or not value.startswith("https://"):
            warnings.append(f"{name} is {value!r}; set it to the public https:// web app URL "
                            "(OAuth redirects and CORS use it).")
    if not os.environ.get("CONTENT_FLOW_DATABASE_URL", "").strip():
        warnings.append("CONTENT_FLOW_DATABASE_URL is not set: using a SQLite file, which a host without a "
                        "persistent disk erases on every restart or redeploy. Set a PostgreSQL URL (e.g. Neon).")
    if not os.environ.get("CLOUDINARY_URL", "").strip():
        warnings.append("CLOUDINARY_URL is not set: uploads are stored on local disk, which a host without a "
                        "persistent disk erases, and proxied uploads are limited by the web host.")
    if os.environ.get("CONTENT_FLOW_COOKIE_SECURE", "").lower() != "true":
        warnings.append("CONTENT_FLOW_COOKIE_SECURE is not 'true'.")
    return warnings



def env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value



def publisher_is_enabled() -> bool:
    value = os.environ.get("CONTENT_FLOW_PUBLISHER_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_ENABLED must be a boolean value.")
    return value in {"true", "1", "yes", "on"}


def publisher_interval_seconds() -> int:
    try:
        interval = int(os.environ.get("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS", "60"))
    except ValueError as error:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS must be an integer.") from error
    if interval < 5:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS must be at least 5.")
    return interval
