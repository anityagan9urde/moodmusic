import numpy as np
import pytest

from moodmusic.vision import emotion
from moodmusic.vision.emotion import HSEmotionModel


class FakeRecognizer:
    def __init__(self, out):
        self.out = out

    def predict_emotions(self, img, logits=True):
        assert logits is True
        return "Happiness", self.out


def make_model(monkeypatch, row):
    out = np.array(row, dtype=float)
    monkeypatch.setattr(emotion, "HSEmotionRecognizer", lambda model_name: FakeRecognizer(out))
    return HSEmotionModel()


def test_hsemotion_maps_output(monkeypatch):
    m = make_model(monkeypatch, [0, 0, 0, 0, 0.9, 0.1, 0, 0, 0.6, 0.3])
    r = m.predict(np.zeros((224, 224, 3), np.uint8))
    assert set(r.probs) == {"anger", "contempt", "disgust", "fear",
                            "happiness", "neutral", "sadness", "surprise"}
    assert max(r.probs, key=r.probs.get) == "happiness"
    assert sum(r.probs.values()) == pytest.approx(1.0)
    assert r.valence == pytest.approx(0.6)
    assert r.arousal == pytest.approx(0.3)


def test_valence_clamped(monkeypatch):
    m = make_model(monkeypatch, [0, 0, 0, 0, 0.9, 0.1, 0, 0, 1.7, -2.0])
    r = m.predict(np.zeros((224, 224, 3), np.uint8))
    assert r.valence == 1.0
    assert r.arousal == -1.0


def test_install_bundled_model_copies_once(monkeypatch, tmp_path):
    src = tmp_path / "bundle.onnx"
    src.write_bytes(b"onnx")
    monkeypatch.setattr(emotion, "resource_path", lambda n: src if n == "m.onnx" else None)
    cache = tmp_path / "cache"
    assert emotion.install_bundled_model("m", cache) is True
    assert (cache / "m.onnx").read_bytes() == b"onnx"
    src.write_bytes(b"changed")
    assert emotion.install_bundled_model("m", cache) is True  # cached copy kept
    assert (cache / "m.onnx").read_bytes() == b"onnx"


def test_install_bundled_model_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(emotion, "resource_path", lambda n: None)
    assert emotion.install_bundled_model("m", tmp_path / "c") is False
