"""`--selftest`: load both vision models and run them on a blank frame. No camera, Spotify or UI."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np


def run_selftest(make_tracker: Callable[[], object] | None = None,
                 make_model: Callable[[], object] | None = None,
                 out: Path | str | None = None) -> int:
    """Print SELFTEST OK (exit 0) or SELFTEST FAILED: <reason> (exit 1).

    The result line also goes to stderr and, if given, to the file `out` (a windowed Windows
    exe has no console, so CI reads the file).
    """
    import sys
    try:
        if make_tracker is None:
            from moodmusic.vision.face import FaceTracker as make_tracker
        if make_model is None:
            from moodmusic.vision.emotion import HSEmotionModel as make_model
        tracker, model = make_tracker(), make_model()
        tracker.process(np.zeros((480, 640, 3), np.uint8), 0)
        model.predict(np.zeros((224, 224, 3), np.uint8))
        line, code = "SELFTEST OK", 0
    except Exception as exc:
        line, code = f"SELFTEST FAILED: {exc}", 1
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:  # None in a windowed exe
            try:
                print(line, file=stream, flush=True)
            except Exception:
                pass
    if out is not None:
        try:
            Path(out).write_text(line + "\n", encoding="utf-8")
        except OSError:
            pass
    return code
