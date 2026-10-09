"""Per-user learning log persistence as local JSON files (one file per user).

Swap this for a database-backed store later without touching callers — they
only depend on `get_log` / `save_log`.
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.schemas import LearningLog


class SessionStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or settings.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, user_id: str) -> Path:
        safe_id = user_id.replace("/", "_").replace("\\", "_")
        return self._data_dir / f"{safe_id}.json"

    def get_log(self, user_id: str) -> LearningLog:
        path = self._path_for(user_id)
        if path.exists():
            return LearningLog.model_validate_json(path.read_text(encoding="utf-8"))
        return LearningLog(user_id=user_id)

    def save_log(self, log: LearningLog) -> None:
        path = self._path_for(log.user_id)
        path.write_text(log.model_dump_json(indent=2), encoding="utf-8")
