"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000
Then open: http://localhost:8000/
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Dutch Tutor Agent")
app.include_router(api_router)

# Serve the simple chat/voice UI directly, so there's no separate dev server
# and no CORS configuration needed.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
