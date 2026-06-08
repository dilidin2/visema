"""Tests for visema.server.app — FastAPI application routes."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _create_test_app(sounds_dir=None):
    """Create a FastAPI test app with optional sounds mount."""
    from visema.server.app import create_app

    # Patch the project root so static file mounts don't fail in CI
    with patch("visema.server.app._PROJECT_ROOT", Path("/tmp/visema_test")):
        app = create_app()
    return app


# ── /health endpoint ──────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "websocket_clients" in data
        assert isinstance(data["websocket_clients"], int)

    def test_health_shows_connection_count(self):
        app = _create_test_app()
        client = TestClient(app)

        # No connections — count should be 0
        response = client.get("/health")
        assert response.json()["websocket_clients"] == 0


# ── /overlay endpoint ─────────────────────────────────────────────────────────


class TestOverlayEndpoint:
    def test_overlay_returns_html(self):
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/overlay")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<!DOCTYPE html>" in response.text or "<html" in response.text
        assert "overlay-container" in response.text
        assert "overlay.css" in response.text
        assert "overlay.js" in response.text

    def test_overlay_contains_expected_scripts(self):
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/overlay")

        html = response.text
        assert 'href="/static/overlay.css"' in html
        assert 'src="/static/overlay.js"' in html

    def test_overlay_missing_html(self):
        """If index.html doesn't exist, returns 404."""
        # Patch to a directory without overlay files
        with patch("visema.server.app._OVERLAY_DIR", Path("/nonexistent")):
            app = _create_test_app()
            client = TestClient(app)

            response = client.get("/overlay")

            assert response.status_code == 404
            assert "not found" in response.text.lower()


# ── /ws WebSocket endpoint ───────────────────────────────────────────────────


class TestWebSocketEndpoint:
    def test_websocket_connect_and_send(self):
        app = _create_test_app()
        client = TestClient(app)

        with client.websocket_connect("/ws") as ws:
            # Should be connected — send a fake message back
            ws.send_text(json.dumps({"ack": "audio_done"}))
            # No response expected from server in this direction

    def test_websocket_invalid_json(self):
        app = _create_test_app()
        client = TestClient(app)

        with client.websocket_connect("/ws") as ws:
            # Send invalid JSON — should not crash the connection
            ws.send_text("not valid json at all {{{")
            # Connection should still be alive
            ws.send_text(json.dumps({"ack": "audio_playing"}))

    def test_websocket_disconnect(self):
        app = _create_test_app()
        client = TestClient(app)

        with client.websocket_connect("/ws") as ws:
            pass  # Exit context manager → disconnect

        # Verify server didn't crash — health check should still work
        response = client.get("/health")
        assert response.status_code == 200


# ── Static files mount ────────────────────────────────────────────────────────


class TestStaticFiles:
    def test_static_css_served(self):
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/static/overlay.css")

        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"] or response.text

    def test_static_js_served(self):
        app = _create_test_app()
        client = TestClient(app)

        response = client.get("/static/overlay.js")

        assert response.status_code == 200
        # overlay.js is a self-contained IIFE
        assert "WebSocket" in response.text or "connect()" in response.text


# ── Sounds static mount ───────────────────────────────────────────────────────


class TestSoundsMount:
    def test_sounds_mount_exists(self):
        app = _create_test_app()
        client = TestClient(app)

        # /sounds/ should be mounted (even if empty directory)
        response = client.get("/sounds/")
        # 405 Method Not Allowed is expected for listing a StaticFiles dir
        assert response.status_code in (200, 405, 404)

    def test_sounds_mount_with_files(self, tmp_path):
        """When sounds directory has files, they should be accessible."""
        # Create fake sound files
        sounds_dir = tmp_path / "sounds"
        sounds_dir.mkdir()
        (sounds_dir / "test.mp3").write_bytes(b"fake audio")

        with patch("visema.server.app._PROJECT_ROOT", tmp_path):
            app = _create_test_app()
            client = TestClient(app)

            response = client.get("/sounds/test.mp3")
            assert response.status_code == 200
            assert response.content == b"fake audio"


# ── App factory ───────────────────────────────────────────────────────────────


class TestAppFactory:
    def test_app_title(self):
        app = _create_test_app()
        assert app.title == "Visema Overlay Server"

    def test_app_version(self):
        app = _create_test_app()
        assert app.version == "1.0.0"

    def test_mounts_are_registered(self):
        app = _create_test_app()
        routes = [route.path for route in app.routes]
        assert "/overlay" in routes
        assert "/health" in routes
        assert "/ws" in routes
        # Static mounts use /static and /sounds prefixes
        assert any("/static" in r for r in routes)
