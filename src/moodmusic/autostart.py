"""Start Mood Music when the user logs in (Windows: the per-user Run registry key)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "MoodMusic"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class WindowsRunKey:
    def set(self, name: str, value: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


def launch_command(frozen: bool | None = None, executable: str | None = None) -> str:
    """The command that starts the app without a console window."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = Path(executable or sys.executable)
    if frozen:
        return f'"{exe}"'
    pythonw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    return f'"{pythonw}" -m moodmusic'


def set_start_at_login(enabled: bool, *, platform: str = sys.platform, run_key=None,
                       command: str | None = None) -> bool:
    """Turn start-at-login on or off. False when this platform isn't supported yet."""
    if platform != "win32":
        return False
    key = run_key or WindowsRunKey()
    try:
        if enabled:
            key.set(APP_NAME, command or launch_command())
        else:
            key.delete(APP_NAME)
    except OSError:
        log.exception("Could not change start at login")
        return False
    return True
