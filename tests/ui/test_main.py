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
