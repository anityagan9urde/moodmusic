import json

import pytest

from moodmusic.mood.calibration import (
    Baseline,
    Calibrator,
    apply_baseline,
    load_baseline,
    save_baseline,
)
from moodmusic.vision.types import EmotionReading


def reading(v, a, neutral):
    probs = {k: 0.0 for k in "anger contempt disgust fear happiness neutral sadness surprise".split()}
    probs["neutral"] = neutral
    return EmotionReading(probs=probs, valence=v, arousal=a)


def calibrated(duration=20.0, n=100, v=-0.35, a=-0.1, neutral=0.3):
    c = Calibrator(duration_s=duration)
    for i in range(n):
        c.add(reading(v, a, neutral), t=i * duration / (n - 1))
    return c


def test_resting_sad_face_becomes_neutral():
    c = calibrated()
    assert c.done
    b = c.result()
    r = apply_baseline(reading(-0.35, -0.1, 0.3), b)
    assert abs(r.valence) < 0.05 and abs(r.arousal) < 0.05  # resting face reads as neutral
    assert r.probs["neutral"] >= 0.6


def test_real_smile_still_upbeat():
    b = calibrated().result()
    r = apply_baseline(reading(0.4, 0.3, 0.1), b)
    assert r.valence > 0.5 and r.arousal > 0.3  # a real smile is clearly positive and lively
    assert r.probs["neutral"] < 0.6


def test_too_few_samples_raises():
    c = Calibrator()
    for i in range(19):
        c.add(reading(0, 0, 0.5), t=i)
    with pytest.raises(ValueError):
        c.result()


def test_progress():
    c = Calibrator(duration_s=20.0)
    assert c.progress == 0.0
    c.add(reading(0, 0, 0.5), t=100.0)
    assert c.progress == 0.0
    c.add(reading(0, 0, 0.5), t=110.0)
    assert c.progress == 0.5
    assert not c.done
    c.add(reading(0, 0, 0.5), t=150.0)
    assert c.progress == 1.0
    assert c.done


def test_apply_clamps_and_caps():
    b = Baseline(valence=-0.8, arousal=0.0, neutral_prob_scale=3.0)
    r = apply_baseline(reading(0.9, 0.0, 0.5), b)
    assert r.valence == 1.0
    assert r.probs["neutral"] == 1.0


def test_roundtrip(tmp_path):
    p = tmp_path / "baseline.json"
    assert load_baseline(p) is None
    b = Baseline(0.1, -0.2, 1.5)
    save_baseline(b, p)
    assert load_baseline(p) == b
    assert set(json.loads(p.read_text())) == {"valence", "arousal", "neutral_prob_scale"}


def test_corrupt_file_returns_none(tmp_path):
    p = tmp_path / "baseline.json"
    p.write_text("{nope")
    assert load_baseline(p) is None
