import numpy as np

import moodmusic
from moodmusic import selftest
from moodmusic.vision.types import EmotionReading


class FakeTracker:
    def __init__(self):
        self.frames = []

    def process(self, frame, ts):
        self.frames.append(frame)
        return None


class FakeModel:
    def predict(self, face):
        return EmotionReading(probs={"neutral": 1.0}, valence=0.0, arousal=0.0)


def test_selftest_flag(capsys):
    code = selftest.run_selftest(FakeTracker, FakeModel)
    assert code == 0
    assert "SELFTEST OK" in capsys.readouterr().out


def test_selftest_failure_exits_1(capsys):
    def boom():
        raise RuntimeError("no model")

    code = selftest.run_selftest(FakeTracker, boom)
    assert code == 1
    assert "SELFTEST FAILED: no model" in capsys.readouterr().out


def test_selftest_writes_out_file(tmp_path):
    out = tmp_path / "r.txt"
    assert selftest.run_selftest(FakeTracker, FakeModel, out=out) == 0
    assert out.read_text().strip() == "SELFTEST OK"


def test_main_dispatches_selftest(monkeypatch):
    from moodmusic import __main__ as entry
    seen = {}
    def fake(*a, out=None, **k):
        seen["out"] = out
        return 0

    monkeypatch.setattr(selftest, "run_selftest", fake)
    assert entry.main(["--selftest", "--selftest-out", "x.txt"]) == 0
    assert str(seen["out"]) == "x.txt"


def test_version():
    assert moodmusic.__version__ == "0.1.0"
