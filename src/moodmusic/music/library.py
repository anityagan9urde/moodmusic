"""SQLite-backed cache of the user's songs and their mood groups."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from moodmusic.mood.groups import MoodGroup


@dataclass
class Song:
    uri: str
    title: str
    artist: str
    album_art: str | None
    group: MoodGroup
    tags: list[str] = field(default_factory=list)
    source: str = "none"  # "track" | "artist" | "user" | "none"
    override: bool = False


_COLS = "uri, title, artist, album_art, grp, tags, source, override"


def _row(r) -> Song:
    return Song(r[0], r[1], r[2], r[3], MoodGroup(r[4]), json.loads(r[5]), r[6], bool(r[7]))


class SongLibrary:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS songs ("
                "uri TEXT PRIMARY KEY, title TEXT, artist TEXT, album_art TEXT, "
                "grp TEXT NOT NULL, tags TEXT NOT NULL, source TEXT NOT NULL, "
                "override INTEGER NOT NULL DEFAULT 0)"
            )
            self._db.commit()

    def upsert(self, song: Song) -> None:
        with self._lock:
            cur = self._db.execute("SELECT grp, override FROM songs WHERE uri=?", (song.uri,))
            existing = cur.fetchone()
            group, override = song.group, song.override
            source = song.source
            if existing and existing[1]:
                group, override = MoodGroup(existing[0]), True
                source = "user"
            self._db.execute(
                f"INSERT OR REPLACE INTO songs ({_COLS}) VALUES (?,?,?,?,?,?,?,?)",
                (song.uri, song.title, song.artist, song.album_art, group.value,
                 json.dumps(song.tags), source, int(override)),
            )
            self._db.commit()

    def get(self, uri: str) -> Song | None:
        with self._lock:
            r = self._db.execute(f"SELECT {_COLS} FROM songs WHERE uri=?", (uri,)).fetchone()
        return _row(r) if r else None

    def set_group(self, uri: str, group: MoodGroup, by_user: bool = True) -> None:
        with self._lock:
            if by_user:
                self._db.execute(
                    "UPDATE songs SET grp=?, override=1, source='user' WHERE uri=?",
                    (group.value, uri))
            else:
                self._db.execute("UPDATE songs SET grp=? WHERE uri=?", (group.value, uri))
            self._db.commit()

    def songs(self, group: MoodGroup | None = None) -> list[Song]:
        with self._lock:
            if group is None:
                rows = self._db.execute(f"SELECT {_COLS} FROM songs").fetchall()
            else:
                rows = self._db.execute(
                    f"SELECT {_COLS} FROM songs WHERE grp=?", (group.value,)).fetchall()
        return [_row(r) for r in rows]

    def uris(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT uri FROM songs")}

    def remove(self, uris: set[str]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM songs WHERE uri=?", [(u,) for u in uris])
            self._db.commit()

    def counts(self) -> dict[MoodGroup, int]:
        with self._lock:
            rows = self._db.execute("SELECT grp, COUNT(*) FROM songs GROUP BY grp").fetchall()
        return {MoodGroup(g): n for g, n in rows}

    def close(self) -> None:
        with self._lock:
            self._db.close()
