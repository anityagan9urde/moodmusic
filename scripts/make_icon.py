"""Regenerate packaging/icon.ico from the tray icon (needs PySide6)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from moodmusic.ui.tray import make_icon  # noqa: E402

app = QGuiApplication([])
ok = make_icon().pixmap(256, 256).save(str(ROOT / "packaging" / "icon.ico"), "ICO")
print("saved" if ok else "failed")
