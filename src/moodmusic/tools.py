"""Library sorting tools, for re-sorting songs by hand or with Claude's help.

    python -m moodmusic.tools export-unsorted [--all] [--out FILE]
    python -m moodmusic.tools apply-sort FILE

Export writes uri<TAB>title<TAB>artist<TAB>group. apply-sort reads uri<TAB>group (extra
columns are ignored, so an edited export works); `unsorted` clears a song's override.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from moodmusic.config import data_dir
from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import SongLibrary


def export_rows(library: SongLibrary, all_songs: bool) -> list[str]:
    songs = library.songs() if all_songs else library.songs(MoodGroup.UNSORTED)
    return [f"{s.uri}\t{s.title}\t{s.artist}\t{s.group.value}" for s in songs]


def apply_lines(library: SongLibrary, lines: list[str]) -> tuple[int, list[str]]:
    """Apply uri<TAB>…<TAB>group lines. Returns (applied, error messages with line numbers)."""
    applied, errors = 0, []
    known = library.uris()
    for n, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            errors.append(f"line {n}: expected uri<TAB>group")
            continue
        uri, name = cols[0].strip(), cols[-1].strip().lower()
        try:
            group = MoodGroup(name)
        except ValueError:
            errors.append(f"line {n}: unknown group '{name}'")
            continue
        if uri not in known:
            errors.append(f"line {n}: unknown song {uri}")
            continue
        library.set_group(uri, group, by_user=group != MoodGroup.UNSORTED)
        if group == MoodGroup.UNSORTED:
            library.clear_override(uri)
        applied += 1
    return applied, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m moodmusic.tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("export-unsorted", help="list songs for sorting")
    exp.add_argument("--all", action="store_true", help="every song, not just unsorted ones")
    exp.add_argument("--out", type=Path, help="write to a file instead of the screen")
    app = sub.add_parser("apply-sort", help="apply a uri<TAB>group file")
    app.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    library = SongLibrary(data_dir() / "library.db")
    try:
        if args.cmd == "export-unsorted":
            text = "\n".join(export_rows(library, args.all)) + "\n"
            if args.out:
                args.out.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            return 0
        lines = args.file.read_text(encoding="utf-8").splitlines()
        applied, errors = apply_lines(library, lines)
        skipped = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#")) - applied
        print(f"applied {applied}, skipped {skipped}")
        for e in errors:
            print("  " + e)
        return 1 if errors else 0
    finally:
        library.close()


if __name__ == "__main__":
    raise SystemExit(main())
