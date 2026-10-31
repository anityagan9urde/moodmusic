"""Persistent user settings and app paths."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import platformdirs

log = logging.getLogger(__name__)

# GitHub "owner/repo" for update checks; empty disables the check.
UPDATE_REPO = ""

HOLD_SECONDS = {"relaxed": 90, "normal": 45, "responsive": 20}


@dataclass
class Settings:
    spotify_client_id: str = ""
    lastfm_api_key: str = ""
    source_playlist_id: str | None = None  # None = Liked Songs
    camera_index: int = 0
    sensitivity: str = "normal"
    switch_mode: str = "wait"  # "wait" or "immediate"
    away_pause_minutes: int = 10  # 0 = off
    mode: str = "match"
    view: str = "simple"
    start_at_login: bool = False
    setup_complete: bool = False


def data_dir() -> Path:
    path = Path(platformdirs.user_data_dir("MoodMusic"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path(path: Path | None) -> Path:
    return path if path is not None else data_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    p = _settings_path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings file is not a JSON object")
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as exc:
        log.warning("Could not read settings from %s (%s); using defaults", p, exc)
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(s: Settings, path: Path | None = None) -> None:
    """Atomic: write a temp file next to the target, then os.replace() it."""
    p = _settings_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(asdict(s), indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
