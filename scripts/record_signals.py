"""Spike: record per-frame face signals (numbers only, never images) through prompted segments.

Run from the project root:  .venv\\Scripts\\python scripts\\record_signals.py
Writes signals-<timestamp>.csv in the current directory and prints per-segment means.
"""
from __future__ import annotations

import csv
import sys
import time
from dataclasses import asdict, fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodmusic.config import load_settings  # noqa: E402
from moodmusic.vision.camera import CameraSource  # noqa: E402
from moodmusic.vision.emotion import HSEmotionModel  # noqa: E402
from moodmusic.vision.face import FaceTracker, crop_face  # noqa: E402
from moodmusic.vision.signals import FrameSignals, extract_signals  # noqa: E402

SEGMENTS = [
    ("screen", "Look at the screen normally", 15),
    ("away", "Look away to the side, as if thinking", 15),
    ("up", "Look up, thinking", 15),
    ("blink", "Look at the screen and blink normally", 15),
    ("yawn", "Yawn twice (or fake it)", 12),
    ("smile", "Smile", 10),
    ("frown", "Frown while reading something on screen", 15),
    ("talk", "Talk as if you're on a call", 15),
]
REPORT = ["gaze_on_screen", "gaze_x", "gaze_y", "head_yaw", "head_pitch", "eye_open",
          "jaw_open", "brow_down", "smile", "mouth_motion"]
FPS = 8


def main() -> int:
    settings = load_settings()
    cam = CameraSource(settings.camera_index)
    tracker, model = FaceTracker(), HSEmotionModel()
    cols = ["segment", "t"] + [f.name for f in fields(FrameSignals) if f.name != "emotion"]
    out = Path(f"signals-{time.strftime('%Y%m%d-%H%M%S')}.csv")
    rows: list[dict] = []
    try:
        for seg, prompt, secs in SEGMENTS:
            input(f"\nNext: {prompt} for {secs} s. Press Enter to start...")
            prev, end = None, time.monotonic() + secs
            while time.monotonic() < end:
                t0 = time.monotonic()
                frame = cam.read()
                if frame is not None:
                    obs = tracker.process(frame, int(t0 * 1000))
                    reading = model.predict(crop_face(frame, obs.bbox)) if obs.bbox else None
                    s = extract_signals(obs, reading, prev)
                    prev = s
                    row = {k: v for k, v in asdict(s).items() if k != "emotion"}
                    rows.append({"segment": seg, "t": round(t0, 3), **row})
                time.sleep(max(0.0, 1 / FPS - (time.monotonic() - t0)))
            print(f"  done ({sum(r['segment'] == seg for r in rows)} frames)")
    finally:
        cam.release()
        tracker.close()
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} frames to {out.resolve()}\n")
    print("segment".ljust(8) + "".join(k[:11].rjust(12) for k in REPORT))
    for seg, _, _ in SEGMENTS:
        seg_rows = [r for r in rows if r["segment"] == seg and r["face"]]
        if not seg_rows:
            print(seg.ljust(8) + "  (no face)")
            continue
        means = [sum(float(r[k]) for r in seg_rows) / len(seg_rows) for k in REPORT]
        print(seg.ljust(8) + "".join(f"{m:12.3f}" for m in means))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
