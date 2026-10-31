"""Incremental library scanner: sorts source tracks into mood groups via Last.fm tags."""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from moodmusic.mood.groups import MoodGroup
from moodmusic.music.lastfm import LastFmError
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.tags import score_tags

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 5
LASTFM_DOWN_MESSAGE = "Can't reach Last.fm right now. Will retry next time."


@dataclass
class ScanProgress:
    done: int
    total: int
    current: str
    error: str | None = None


def first_artist(artist: str) -> str:
    return artist.split(", ")[0].strip()


class Scanner:
    def __init__(self, service, lastfm, library: SongLibrary):
        self._service = service
        self._lastfm = lastfm
        self._library = library

    def run(
        self,
        playlist_id: str | None,
        on_progress: Callable[[ScanProgress], None],
        should_stop: Callable[[], bool],
    ) -> ScanProgress:
        source = list(self._service.iter_source_tracks(playlist_id))
        source_uris = {t[0] for t in source}
        stale = self._library.uris() - source_uris
        if stale:
            self._library.remove(stale)
        known = self._library.uris()
        new = [t for t in source if t[0] not in known]

        progress = ScanProgress(0, len(new), "")
        artist_cache: dict[str, list[tuple[str, int]]] = {}
        failures = 0
        for uri, title, artist, art in new:
            if should_stop():
                break
            lead = first_artist(artist)
            label = f"{artist} – {title}"
            try:
                group, tags, src = self._classify(lead, title, artist_cache)
            except LastFmError as e:
                failures += 1
                log.warning("Last.fm lookup failed for %s: %s", label, type(e).__name__)
                progress = ScanProgress(progress.done + 1, len(new), label)
                on_progress(progress)
                if failures >= MAX_CONSECUTIVE_ERRORS:
                    progress.error = LASTFM_DOWN_MESSAGE
                    return progress
                continue
            failures = 0
            self._library.upsert(Song(uri, title, artist, art, group, tags, src, False))
            progress = ScanProgress(progress.done + 1, len(new), label)
            on_progress(progress)
        return progress

    def _classify(self, lead, title, artist_cache):
        group, tags = score_tags(self._lastfm.track_tags(lead, title))
        if group is not None:
            return group, tags, "track"
        key = lead.lower()
        if key not in artist_cache:
            artist_cache[key] = self._lastfm.artist_tags(lead)
        group, tags = score_tags(artist_cache[key])
        if group is not None:
            return group, tags, "artist"
        return MoodGroup.UNSORTED, [], "none"


def _best(counts: Counter) -> MoodGroup | None:
    """Most common group; ties go to the group declared first in MoodGroup."""
    if not counts:
        return None
    order = list(MoodGroup)
    return max(counts, key=lambda g: (counts[g], -order.index(g)))


def suggest_group(song: Song, library: SongLibrary) -> MoodGroup | None:
    lead = first_artist(song.artist).lower()
    return _best(Counter(
        s.group
        for s in library.songs()
        if s.uri != song.uri
        and s.group != MoodGroup.UNSORTED
        and first_artist(s.artist).lower() == lead
    ))


def suggest_groups(songs: list[Song]) -> dict[str, MoodGroup | None]:
    """suggest_group() for every Unsorted song in one pass over `songs` (all songs)."""
    by_artist: dict[str, Counter] = {}
    for s in songs:
        if s.group != MoodGroup.UNSORTED:
            by_artist.setdefault(first_artist(s.artist).lower(), Counter())[s.group] += 1
    # An Unsorted song is never in its own counts, so excluding it is automatic.
    return {s.uri: _best(by_artist.get(first_artist(s.artist).lower(), Counter()))
            for s in songs if s.group == MoodGroup.UNSORTED}
