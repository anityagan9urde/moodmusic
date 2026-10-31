from moodmusic.config import Settings
from moodmusic.ui.dashboard import Dashboard
from moodmusic.ui.main import ViewManager
from moodmusic.ui.widget import MoodWidget


def test_switch_views_persists_setting(qtbot, engine, worker):
    saved = []
    settings = Settings(view="simple")
    engine.settings = settings
    w = MoodWidget(engine, worker, save=lambda s: None)
    d = Dashboard(engine, worker, save=lambda s: None)
    qtbot.addWidget(w)
    qtbot.addWidget(d)
    vm = ViewManager(settings, w, d, save=lambda s: saved.append(s.view))
    vm.show_view("advanced")
    assert settings.view == "advanced"
    assert saved == ["advanced"]
    assert d.isVisible() and not w.isVisible()
    w.switch_view.emit("simple")
    assert settings.view == "simple"
    assert saved == ["advanced", "simple"]
    assert w.isVisible() and not d.isVisible()


def test_close_hides_instead_of_quitting(qtbot, engine, worker):
    w = MoodWidget(engine, worker, save=lambda s: None)
    qtbot.addWidget(w)
    w.show()
    w.close()
    assert not w.isVisible()


def test_tray_pause_and_view_label(qtbot, engine, worker):
    from moodmusic.ui.tray import Tray
    settings = Settings(view="simple")
    engine.settings = settings
    w = MoodWidget(engine, worker, save=lambda s: None)
    d = Dashboard(engine, worker, save=lambda s: None)
    qtbot.addWidget(w)
    qtbot.addWidget(d)
    vm = ViewManager(settings, w, d, save=lambda s: None)
    quits, sets = [], []
    tray = Tray(engine, vm, lambda: sets.append(1), lambda: quits.append(1))
    assert tray.toggle_view_action.text() == "Advanced view"
    tray.pause_action.toggle()
    assert engine.calls[-1] == ("set_enabled", False)
    tray.pause_action.toggle()
    assert engine.calls[-1] == ("set_enabled", True)
    tray.toggle_view_action.trigger()
    assert settings.view == "advanced"
    tray.update_view_label()
    assert tray.toggle_view_action.text() == "Simple view"
    tray.settings_action.trigger()
    tray.quit_action.trigger()
    assert sets == [1] and quits == [1]


def test_engine_bridge_forwards_worker_signals(qtbot, worker):
    from moodmusic.ui.main import EngineBridge

    class Rec:
        def __init__(self):
            self.got = []

        def on_mood(self, s): self.got.append(("mood", s))
        def on_quality(self, r): self.got.append(("quality", r))
        def on_face_present(self, p): self.got.append(("face", p))

    rec = Rec()
    bridge = EngineBridge(rec, worker)  # noqa: F841
    worker.mood.emit("m")
    worker.quality.emit("q")
    worker.face_present.emit(True)
    assert rec.got == [("mood", "m"), ("quality", "q"), ("face", True)]


def test_report_scan_messages():
    from moodmusic.music.scanner import ScanProgress
    from moodmusic.ui.main import report_scan
    out = []
    note = lambda t, m: out.append(m)  # noqa: E731
    report_scan(ScanProgress(1, 1, "x"), note)
    assert out == []
    report_scan(ScanProgress(1, 2, "x", error="Last.fm down"), note)
    report_scan(None, note)
    assert out[0] == "Last.fm down" and "scan failed" in out[1]


def test_scan_thread_emits_result_or_none(qtbot):
    from moodmusic.ui.main import ScanThread

    class Ok:
        def run(self, pid, on_progress, should_stop):
            return "result"

    class Boom:
        def run(self, pid, on_progress, should_stop):
            raise RuntimeError("x")

    for scanner, expected in ((Ok(), "result"), (Boom(), None)):
        t = ScanThread(scanner, None)
        with qtbot.waitSignal(t.finished_with, timeout=3000) as sig:
            t.start()
        assert sig.args == [expected]
        assert t.stop() is True


def test_run_wizard_missing_shows_message(monkeypatch):
    import sys
    from PySide6.QtWidgets import QMessageBox
    from moodmusic.ui import main
    monkeypatch.setitem(sys.modules, "moodmusic.ui.wizard", None)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: shown.append(a[2])))
    assert main._run_wizard(Settings()) is None
    assert shown == ["Setup isn't available yet"]


def test_scan_controller_runs_one_at_a_time(qtbot):
    from moodmusic.ui.main import ScanController

    class Scanner:
        def run(self, pid, on_progress, should_stop):
            on_progress("p")
            return "done"

    c = ScanController(lambda: Scanner(), lambda: None)
    with qtbot.waitSignal(c.finished_with, timeout=3000) as fin:
        c.rescan()
    assert fin.args == ["done"]
    qtbot.waitUntil(lambda: not c.is_running(), timeout=3000)
    assert c.stop() is True
