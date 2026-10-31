# PyInstaller spec: one-dir, windowed. Build from the repo root:
#   python scripts/fetch_models.py
#   pyinstaller packaging/moodmusic.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
RES = ROOT / "src" / "moodmusic" / "resources"

datas = collect_data_files("mediapipe")
binaries = collect_dynamic_libs("mediapipe") + collect_dynamic_libs("onnxruntime")
# Bundled models (and the optional Last.fm key) land in <bundle>/moodmusic/resources.
for pattern in ("*.task", "*.onnx", "lastfm_key.txt"):
    for f in RES.glob(pattern):
        datas.append((str(f), "moodmusic/resources"))

icon = ROOT / "packaging" / "icon.ico"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=["keyring.backends.Windows", "keyring.backends.macOS"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtQuick"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MoodMusic",
    console=False,
    icon=str(icon) if sys.platform == "win32" and icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MoodMusic")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MoodMusic.app",
        bundle_identifier="app.moodmusic",
        info_plist={
            "NSCameraUsageDescription": (
                "Mood Music reads your expression locally to choose music. "
                "Video never leaves your computer."),
            "CFBundleShortVersionString": "0.1.0",
            "LSUIElement": False,
        },
    )
