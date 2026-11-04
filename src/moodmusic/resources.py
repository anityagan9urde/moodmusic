"""Locate bundled data files (models, optional Last.fm key) from source or a PyInstaller bundle."""
from __future__ import annotations

import sys
from pathlib import Path


def resources_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:  # frozen: the spec places data under <bundle>/moodmusic/resources
        return Path(base) / "moodmusic" / "resources"
    return Path(__file__).resolve().parent / "resources"


def resource_path(name: str) -> Path | None:
    """The bundled file if present, else None."""
    p = resources_dir() / name
    return p if p.is_file() else None
