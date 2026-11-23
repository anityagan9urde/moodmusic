import json

import pytest

from moodmusic.mood.baselines import (DEFAULTS, KEYS, SAMPLE_EVERY_S, PersonalBaselines,
                                      load_baselines, save_baselines)
from moodmusic.mood.features import Features


def run(b: PersonalBaselines, minutes: float, **feat) -> None:
    """Feed `minutes` of 0.5 s updates with face present."""
    f = Features(face_ratio_10s=1.0, **feat)
    for _ in range(int(minutes * 60 / 0.5)):
        b.update(f, 0.5)


def test_get_falls_back_to_default_until_samples():
    b = PersonalBaselines()
    assert b.get("blink_rate_per_min_60s") == DEFAULTS["blink_rate_per_min_60s"]
    assert b.get("unknown_key", 7.0) == 7.0
    run(b, 0.25, blink_rate_per_min_60s=30)  # 3 samples: not enough yet
    assert b.get("blink_rate_per_min_60s") == DEFAULTS["blink_rate_per_min_60s"]


def test_rolling_median_tracks_value():
    b = PersonalBaselines()
    run(b, 30, blink_rate_per_min_60s=25)
    assert b.get("blink_rate_per_min_60s") == pytest.approx(25)


def test_rolling_median_follows_a_shift_within_the_hour():
    b = PersonalBaselines()
    run(b, 20, head_motion_30s=2.0)
    run(b, 60, head_motion_30s=6.0)
    assert b.get("head_motion_30s") == pytest.approx(6.0)


def test_absent_face_is_not_sampled():
    b = PersonalBaselines()
    f = Features(face_ratio_10s=0.0, blink_rate_per_min_60s=99)
    for _ in range(600):
        b.update(f, 0.5)
    assert b.observed_s == 0
    assert b.get("blink_rate_per_min_60s") == DEFAULTS["blink_rate_per_min_60s"]


def test_warm_after_1800s():
    b = PersonalBaselines()
    run(b, 29.9)
    assert not b.warm
    run(b, 0.2)
    assert b.warm


def test_calibrate_rest_sets_at_rest_keys():
    b = PersonalBaselines()
    b.calibrate_rest(Features(brow_down_30s=0.3, mouth_press_30s=0.2, smile_10s=0.1,
                              gaze_on_ratio_30s=0.9, head_droop_deg_240s=-10))
    assert b.get("brow_down_30s") == pytest.approx(0.3)
    assert b.get("head_droop_deg_240s") == pytest.approx(-10)
    assert b.get("blink_rate_per_min_60s") == DEFAULTS["blink_rate_per_min_60s"]  # not a rest key
    run(b, 10, brow_down_30s=0.1)  # enough passive data overrides calibration
    assert b.get("brow_down_30s") == pytest.approx(0.1)


def test_persist_roundtrip_and_corrupt_file(tmp_path):
    p = tmp_path / "sb.json"
    b = PersonalBaselines()
    run(b, 5, blink_rate_per_min_60s=18)
    b.calibrate_rest(Features(smile_10s=0.2))
    save_baselines(b, p)
    again = load_baselines(p)
    assert again.get("blink_rate_per_min_60s") == pytest.approx(18)
    assert all(again.get(k) == pytest.approx(b.get(k)) for k in KEYS)
    assert again.observed_s == pytest.approx(b.observed_s)
    rest_only = PersonalBaselines()
    rest_only.calibrate_rest(Features(smile_10s=0.2))
    save_baselines(rest_only, p)
    assert load_baselines(p).get("smile_10s") == pytest.approx(0.2)
    assert set(json.loads(p.read_text())["samples"]) <= set(KEYS)
    p.write_text("{not json")
    assert load_baselines(p).observed_s == 0
    assert load_baselines(tmp_path / "missing.json").observed_s == 0


def test_sampling_interval_constant():
    assert SAMPLE_EVERY_S == 15


def test_not_sampled_while_another_state_is_active():
    b = PersonalBaselines()
    f = Features(face_ratio_10s=1.0, blink_rate_per_min_60s=40)
    for _ in range(3600):  # 30 min of a detected state (e.g. Tired)
        b.update(f, 0.5, sample=False)
    assert b.get("blink_rate_per_min_60s") == DEFAULTS["blink_rate_per_min_60s"]
    assert b.observed_s == pytest.approx(1800)  # time still counts toward warm-up


def test_long_window_resists_an_hour_long_state():
    b = PersonalBaselines()
    run(b, 180, head_motion_30s=2.0)  # 3 h of normal work
    run(b, 60, head_motion_30s=9.0)  # then an hour of something else
    assert b.get("head_motion_30s") == pytest.approx(2.0)


def test_brow_raise_and_tilt_have_baselines():
    b = PersonalBaselines()
    b.calibrate_rest(Features(brow_inner_up_10s=0.3, head_tilt_10s=7))
    assert b.get("brow_inner_up_10s") == pytest.approx(0.3)
    assert b.get("head_tilt_10s") == pytest.approx(7)


def test_screen_center_roundtrip(tmp_path):
    b = PersonalBaselines()
    assert b.screen_center is None
    b.screen_center = (0.1, -0.35, 3.0)
    save_baselines(b, tmp_path / "c.json")
    assert load_baselines(tmp_path / "c.json").screen_center == pytest.approx((0.1, -0.35, 3.0))


def test_rest_captures_valence_and_arousal():
    from dataclasses import replace as _r
    from moodmusic.mood.baselines import DEFAULTS, REST_KEYS, PersonalBaselines
    from moodmusic.mood.features import Features
    assert DEFAULTS["valence_30s"] == 0.0 and DEFAULTS["arousal_30s"] == 0.0
    assert "valence_30s" in REST_KEYS and "arousal_30s" in REST_KEYS
    b = PersonalBaselines()
    b.calibrate_rest(_r(Features(), valence_30s=-0.57, arousal_30s=-0.13))
    assert b.get("valence_30s") == -0.57 and b.get("arousal_30s") == -0.13
