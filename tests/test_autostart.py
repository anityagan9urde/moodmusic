from moodmusic import autostart


class FakeKey:
    def __init__(self):
        self.values = {}

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_enable_and_disable_on_windows():
    key = FakeKey()
    assert autostart.set_start_at_login(True, platform="win32", run_key=key, command="X -m y")
    assert key.values == {"MoodMusic": "X -m y"}
    assert autostart.set_start_at_login(False, platform="win32", run_key=key)
    assert key.values == {}


def test_unsupported_platform_reports_false():
    assert not autostart.set_start_at_login(True, platform="darwin", run_key=FakeKey())


def test_launch_command_uses_pythonw_from_source():
    cmd = autostart.launch_command(frozen=False, executable=r"C:\v\Scripts\python.exe")
    assert cmd == r'"C:\v\Scripts\pythonw.exe" -m moodmusic'
    frozen = autostart.launch_command(frozen=True, executable=r"C:\A\MoodMusic.exe")
    assert frozen == r'"C:\A\MoodMusic.exe"'
