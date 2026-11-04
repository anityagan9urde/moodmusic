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


def test_rescan_while_running_queues_exactly_one_followup(qtbot):
    import threading
    from moodmusic.ui.main import ScanController

    started, gate, runs = [], threading.Event(), []

    class Scanner:
        def run(self, pid, on_progress, should_stop):
            runs.append(1)
            if len(runs) == 1:
                started.append(1)
                gate.wait(3)
                assert should_stop()  # the queued rescan asked the first scan to end early
            return len(runs)

    c = ScanController(lambda: Scanner(), lambda: None)
    results = []
    c.finished_with.connect(results.append)
    c.rescan()
    qtbot.waitUntil(lambda: bool(started), timeout=3000)
    c.rescan()
    c.rescan()  # repeated requests still produce a single follow-up
    assert c.is_running()
    gate.set()
    qtbot.waitUntil(lambda: len(results) == 2 and not c.is_running(), timeout=3000)
    qtbot.wait(100)
    assert len(runs) == 2 and len(results) == 2
    assert c.stop() is True


def test_build_scanner_uses_current_client_id():
    from moodmusic.ui.main import build_scanner

    seen = []
    s = Settings(spotify_client_id="old")

    def fake_make(cid):
        seen.append(cid)
        return object()

    build_scanner(s, library=None, make_spotify_fn=fake_make)
    s.spotify_client_id = "new"
    build_scanner(s, library=None, make_spotify_fn=fake_make)
    assert seen == ["old", "new"]


def test_update_check_skipped_without_repo():
    from moodmusic.ui.main import start_update_check
    assert start_update_check(lambda url: None, repo="") is None


def test_update_check_delivers_url_on_gui_thread(qtbot):
    from moodmusic.ui.main import start_update_check
    got = []
    relay = start_update_check(got.append, current="0.1.0", repo="a/b",
                               check=lambda cur, repo: "https://x/r")
    qtbot.waitUntil(lambda: got == ["https://x/r"], timeout=3000)
    assert relay is not None


def test_update_check_silent_when_up_to_date(qtbot):
    from moodmusic.ui.main import start_update_check
    got = []
    start_update_check(got.append, current="0.1.0", repo="a/b", check=lambda c, r: None)
    qtbot.wait(200)
    assert got == []


class _Stoppable:
    def __init__(self, log, name, result=True, running=False):
        self.log, self.name, self.result, self.running = log, name, result, running

    def stop(self):
        self.log.append(self.name)
        return self.result

    def isRunning(self):  # noqa: N802
        return self.running

    def close(self):
        self.log.append(self.name + ".close")

    def shutdown(self):
        self.log.append(self.name)


def test_cleanup_is_idempotent_and_runs_on_about_to_quit(qtbot):
    from PySide6.QtWidgets import QApplication

    from moodmusic.ui.main import make_cleanup
    log = []
    cleanup = make_cleanup(_Stoppable(log, "timer"), _Stoppable(log, "worker"),
                           _Stoppable(log, "scan"), _Stoppable(log, "library"),
                           login=_Stoppable(log, "login"), live_wait_ms=10)
    app = QApplication.instance()
    app.aboutToQuit.connect(cleanup)
    try:
        app.aboutToQuit.emit()
    finally:
        app.aboutToQuit.disconnect(cleanup)
    assert log == ["timer", "login", "scan", "worker", "library.close"]
    assert cleanup() is True and cleanup() is True
    assert log == ["timer", "login", "scan", "worker", "library.close"]  # ran once


def test_cleanup_keeps_library_open_while_scan_runs(qtbot):
    from moodmusic.ui.main import make_cleanup
    log = []
    cleanup = make_cleanup(_Stoppable(log, "timer"), _Stoppable(log, "worker"),
                           _Stoppable(log, "scan", result=False), _Stoppable(log, "library"),
                           live_wait_ms=10)
    assert cleanup() is False and "library.close" not in log


def test_cleanup_survives_failing_steps(qtbot):
    from moodmusic.ui.main import make_cleanup
    log = []

    class Bad(_Stoppable):
        def stop(self):
            raise RuntimeError("x")
    cleanup = make_cleanup(Bad(log, "timer"), _Stoppable(log, "worker"),
                           _Stoppable(log, "scan"), _Stoppable(log, "library"), live_wait_ms=10)
    assert cleanup() is True and "library.close" in log


def test_thread_excepthook_logs(caplog):
    import sys
    import threading

    from moodmusic.ui.main import install_excepthooks
    old_sys, old_thr = sys.excepthook, threading.excepthook
    try:
        install_excepthooks()

        def boom():
            raise ValueError("in thread")
        t = threading.Thread(target=boom, name="tboom")
        with caplog.at_level("ERROR"):
            t.start()
            t.join()
        assert "Unhandled exception in thread tboom" in caplog.text
    finally:
        sys.excepthook, threading.excepthook = old_sys, old_thr


def test_needs_calibration_when_screen_centre_missing():
    from moodmusic.mood.baselines import PersonalBaselines
    from moodmusic.ui.main import needs_calibration
    from moodmusic.mood.calibration import Baseline
    old = Baseline(0.0, 0.0, 1.0, {"anger": 0.2})
    b = PersonalBaselines()
    assert needs_calibration(None, b)
    assert needs_calibration(old, b)  # upgraded install: old baseline, no screen centre
    b.screen_center = (0.0, 0.1, 0.0)
    assert not needs_calibration(old, b)


def test_needs_calibration_when_baseline_has_no_resting_emotions():
    from moodmusic.mood.baselines import PersonalBaselines
    from moodmusic.mood.calibration import Baseline
    from moodmusic.ui.main import needs_calibration
    b = PersonalBaselines()
    b.screen_center = (0.0, 0.1, 0.0)
    assert needs_calibration(Baseline(0.0, 0.0, 1.0), b)
    assert not needs_calibration(Baseline(0.0, 0.0, 1.0, {"anger": 0.2}), b)
