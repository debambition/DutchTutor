"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000
Then open: http://localhost:8000/
"""
from __future__ import annotations

from pathlib import Path

import truststore

# Verify TLS against the OS certificate store instead of certifi's bundle, so
# outbound calls work behind TLS-inspecting corporate proxies (e.g. Zscaler)
# whose root CA is trusted by the OS but not shipped with Python.
truststore.inject_into_ssl()

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.api.routes import router as api_router  # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Dutch Tutor Agent")
app.include_router(api_router)

# Serve the simple chat/voice UI directly, so there's no separate dev server
# and no CORS configuration needed.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
