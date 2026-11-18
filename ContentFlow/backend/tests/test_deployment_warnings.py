"""Hosted deployments warn (in the logs) about settings copied from local development."""
from __future__ import annotations

import pytest

from app import config

LOCAL_LIKE = {"CONTENT_FLOW_API_PUBLIC_URL": "https://abc.ngrok-free.dev", "CONTENT_FLOW_FRONTEND_URL": "http://localhost:3000"}
GOOD = {"CONTENT_FLOW_API_PUBLIC_URL": "https://app.vercel.app", "CONTENT_FLOW_FRONTEND_URL": "https://app.vercel.app",
        "CONTENT_FLOW_DATABASE_URL": "postgresql://u:p@h/db", "CLOUDINARY_URL": "cloudinary://k:s@c",
        "CONTENT_FLOW_COOKIE_SECURE": "true"}


def _apply(monkeypatch: pytest.MonkeyPatch, values: dict, origins: list) -> None:
    for key in ("RENDER", "KOYEB_APP_NAME", "KOYEB_SERVICE_NAME", "CONTENT_FLOW_DATABASE_URL", "CLOUDINARY_URL",
                "CONTENT_FLOW_COOKIE_SECURE", "CONTENT_FLOW_API_PUBLIC_URL", "CONTENT_FLOW_FRONTEND_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", origins)


def test_no_warnings_in_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, LOCAL_LIKE, ["http://localhost:3000"])
    assert config.deployment_warnings() == []


def test_local_values_on_render_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, {**LOCAL_LIKE, "RENDER": "true"}, ["http://localhost:3000"])
    text = " ".join(config.deployment_warnings())
    for name in ("CONTENT_FLOW_API_PUBLIC_URL", "CONTENT_FLOW_FRONTEND_URL", "CONTENT_FLOW_ALLOWED_ORIGINS",
                 "CONTENT_FLOW_DATABASE_URL", "CLOUDINARY_URL", "CONTENT_FLOW_COOKIE_SECURE"):
        assert name in text
    assert "postgresql://" not in text and "cloudinary://" not in text


def test_correct_production_settings_are_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, {**GOOD, "RENDER": "true"}, ["https://app.vercel.app"])
    assert config.deployment_warnings() == []


def test_placeholder_cloudinary_url_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, {**GOOD, "RENDER": "true", "CLOUDINARY_URL": "cloudinary://<your_api_key>:<your_api_secret>@c"},
           ["https://app.vercel.app"])
    assert any("CLOUDINARY_URL is invalid" in w for w in config.deployment_warnings())
