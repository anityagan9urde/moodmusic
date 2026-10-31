"""Pick a song for an intent (ordered song groups), avoiding recent repeats."""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

from moodmusic.mood.groups import MoodGroup, nearest_groups
from moodmusic.music.library import Song, SongLibrary

FRESH_FRACTION = 0.25  # Fresh picks come from the least recently played quarter


@dataclass
class Pick:
    song: Song
    group: MoodGroup
    reason: str
    fell_back_from: MoodGroup | None
    groups: list[MoodGroup] | None = None


class SongSelector:
    def __init__(self, library: SongLibrary, rng: random.Random):
        self.library = library
        self._rng = rng
        self._recent: dict[MoodGroup, deque[str]] = {}

    def mark_played(self, uri: str, now: float | None = None) -> None:
        if now is not None:
            self.library.record_play(uri, now)
        song = self.library.get(uri)
        if song is None:
            return
        dq = self._recent.setdefault(song.group, deque())
        if uri in dq:
            dq.remove(uri)
        dq.append(uri)

    def pick(self, groups: list[MoodGroup], mood, fresh: bool = False,
             now: float = 0.0) -> Pick | None:
        """Pick from `groups` in order, then nearest_groups(groups[0]) as fallback.

        `fresh` pools every song in `groups` and picks among the least recently played.
        """
        groups = list(groups)
        if fresh:
            pool = [s for g in groups for s in self.library.songs(g)]
            if pool:
                song = self._choose_fresh(pool)
                return Pick(song, song.group, self._reason(song, song.group, mood, None, True),
                            None, groups)
        target = groups[0]
        order = groups + [g for g in nearest_groups(target) if g not in groups]
        for group in order:
            songs = self.library.songs(group)
            if not songs:
                continue
            song = self._choose(group, songs)
            fell = target if group not in groups else None
            return Pick(song, group, self._reason(song, group, mood, fell), fell, groups)
        return None

    def _choose_fresh(self, pool: list[Song]) -> Song:
        last = self.library.last_played()
        ranked = sorted(pool, key=lambda s: last.get(s.uri, float("-inf")))
        never = [s for s in ranked if s.uri not in last]
        candidates = never or ranked[:max(1, int(len(ranked) * FRESH_FRACTION))]
        return self._rng.choice(candidates)

    def _choose(self, group: MoodGroup, songs: list[Song]) -> Song:
        size = max(1, int(0.8 * len(songs)))
        dq = self._recent.setdefault(group, deque())
        while len(dq) > size:
            dq.popleft()
        recent = set(dq)
        fresh = [s for s in songs if s.uri not in recent]
        if fresh:
            return self._rng.choice(fresh)
        by_uri = {s.uri: s for s in songs}
        for uri in dq:  # oldest first
            if uri in by_uri:
                return by_uri[uri]
        return self._rng.choice(songs)

    def _reason(self, song: Song, group: MoodGroup, mood,
                fell_back_from: MoodGroup | None, fresh: bool = False) -> str:
        text = f"{group.label}: you seem {_mood_label(mood).lower()}"
        if fresh:
            text += "; something you haven't heard in a while"
        elif song.source == "artist":
            text += "; sorted by artist style"
        elif song.source == "user":
            text += "; you filed it here"
        elif song.tags:
            text += "; tagged " + ", ".join(song.tags[:2])
        if fell_back_from is not None:
            text += f" (no {fell_back_from.label} songs yet)"
        return text


def _mood_label(mood) -> str:
    """Label of the user's face state (FaceMood.state)."""
    return mood.state.label
