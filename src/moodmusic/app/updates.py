"""Optional "update available" check against GitHub releases. Never raises."""
from __future__ import annotations

import logging

import requests

from moodmusic.config import UPDATE_REPO

log = logging.getLogger(__name__)


def _parse(tag: str):
    tag = tag.strip().lstrip("vV")
    try:
        from packaging.version import Version
        return Version(tag)
    except ImportError:
        return tuple(int(p) for p in tag.split("."))


def check_for_update(current: str, repo: str = UPDATE_REPO) -> str | None:
    """Release URL if the latest GitHub release is newer than `current`, else None."""
    if not repo:
        return None
    try:
        resp = requests.get(f"https://api.github.com/repos/{repo}/releases/latest",
                            headers={"Accept": "application/vnd.github+json"}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        url = data["html_url"]
        if _parse(data["tag_name"]) > _parse(current) and isinstance(url, str) and url:
            return url
    except Exception as exc:  # network, JSON, missing keys, unparseable tag
        log.debug("Update check failed: %s", exc)
    return None
