"""
FastAPI application: HTTP routes, static file serving, WebSocket endpoint.
"""

import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from visema.server.ws_manager import _manager, get_manager, set_ack_callback

logger = logging.getLogger(__name__)

# Project root (parent of visema/ package)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_OVERLAY_DIR = _PROJECT_ROOT / "visema" / "overlay"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Visema Overlay Server", version="1.0.0")

    # ── Static files ────────────────────────────────────

    # Overlay CSS/JS served at /static/
    static_dir = _OVERLAY_DIR
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Sounds directory served at /sounds/
    sounds_dir = _PROJECT_ROOT / "sounds"
    if sounds_dir.exists():
        app.mount("/sounds", StaticFiles(directory=str(sounds_dir)), name="sounds")

    # ── Overlay page ────────────────────────────────────

    @app.get("/overlay", response_class=HTMLResponse)
    async def overlay_page():
        """Serve the OBS Browser Source overlay page."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text())
        return HTMLResponse(content="<h1>Overlay not found</h1>", status_code=404)

    # ── WebSocket endpoint ──────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for OBS Browser Sources."""
        await _manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    await _manager.handle_client_ack(websocket, msg)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from WebSocket client: %s", data[:200])
        except Exception:
            logger.debug("WebSocket client disconnected")
        finally:
            await _manager.disconnect(websocket)

    # ── Health check ────────────────────────────────────

    @app.get("/health")
    async def health():
        """Simple health check endpoint."""
        manager = get_manager()
        return {
            "status": "ok",
            "websocket_clients": manager.connection_count,
        }

    return app
