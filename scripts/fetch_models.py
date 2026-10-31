"""Download the vision models into src/moodmusic/resources/ so PyInstaller can bundle them.

Run before building: python scripts/fetch_models.py
"""
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "src" / "moodmusic" / "resources"
sys.path.insert(0, str(ROOT / "src"))

LANDMARKER_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                  "face_landmarker/float16/latest/face_landmarker.task")
ONNX_NAME = "enet_b0_8_va_mtl.onnx"
ONNX_URL = ("https://github.com/HSE-asavchenko/face-emotion-recognition/blob/main/models/"
            f"affectnet_emotions/onnx/{ONNX_NAME}?raw=true")


def fetch(url: str, dest: Path) -> None:
    if dest.is_file() and dest.stat().st_size > 0:
        print("have", dest.name)
        return
    print("downloading", dest.name)
    tmp = dest.with_name(dest.name + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def main() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    fetch(LANDMARKER_URL, RES / "face_landmarker.task")
    cached = Path.home() / ".hsemotion" / ONNX_NAME
    if cached.is_file() and not (RES / ONNX_NAME).is_file():
        shutil.copyfile(cached, RES / ONNX_NAME)
    fetch(ONNX_URL, RES / ONNX_NAME)
    for name in ("face_landmarker.task", ONNX_NAME):
        if (RES / name).stat().st_size < 100_000:
            raise SystemExit(f"{name} looks truncated")


if __name__ == "__main__":
    main()
