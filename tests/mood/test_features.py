import pytest

from moodmusic.mood.features import FeatureTracker
from moodmusic.vision.signals import FrameSignals

DT = 1 / 8


def sig(**kw) -> FrameSignals:
    base = dict(face=True, eye_open=1.0)
    base.update(kw)
    return FrameSignals(**base)


def feed(tr: FeatureTracker, t0: float, seconds: float, make) -> float:
    """Feed `seconds` of frames at 8 Hz; make(t) -> FrameSignals. Returns the end time."""
    n = round(seconds / DT)
    for i in range(n):
        t = t0 + i * DT
        tr.add(make(t), t)
    return t0 + n * DT


def test_gaze_away_hold_grows_and_resets():
    tr = FeatureTracker()
    t = feed(tr, 0, 5, lambda t: sig())
    t = feed(tr, t, 12, lambda t: sig(gaze_x=0.7))
    assert tr.features(t).gaze_away_hold_s == pytest.approx(12, abs=0.3)
    t = feed(tr, t, 1, lambda t: sig())
    assert tr.features(t).gaze_away_hold_s == 0


def test_face_lost_does_not_count_as_gaze_away():
    tr = FeatureTracker()
    t = feed(tr, 0, 20, lambda t: FrameSignals(face=False))
    f = tr.features(t)
    assert f.gaze_away_hold_s == 0
    assert f.face_ratio_10s == 0
    t = feed(tr, t, 4, lambda t: sig(gaze_x=0.7))
    t = feed(tr, t, 2, lambda t: FrameSignals(face=False))
    assert tr.features(t).gaze_away_hold_s == 0  # losing the face resets the hold


def test_blink_rate_and_duration():
    tr = FeatureTracker()
    # 15 blinks of 200 ms in 60 s: closed for 0.2 s every 4 s.
    t = feed(tr, 0, 60, lambda t: sig(eye_open=0.1 if (t % 4) < 0.2 else 1.0))
    f = tr.features(t)
    assert f.blink_rate_per_min_60s == pytest.approx(15, abs=1)
    assert f.mean_blink_ms_60s == pytest.approx(200, abs=60)
    assert f.long_closures_90s == 0


def test_perclos_and_long_closures():
    tr = FeatureTracker()
    # Eyes closed 1.5 s out of every 10 s, for 60 s.
    t = feed(tr, 0, 60, lambda t: sig(eye_open=0.1 if (t % 10) < 1.5 else 1.0))
    f = tr.features(t)
    assert f.long_closures_90s == 6
    assert f.perclos_60s == pytest.approx(0.15, abs=0.03)
    assert f.blink_rate_per_min_60s == pytest.approx(0, abs=0.5)  # long closures aren't blinks


def test_yawn_counted_once_per_event():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig())
    t = feed(tr, t, 3, lambda t: sig(jaw_open=0.8))  # one long yawn
    t = feed(tr, t, 5, lambda t: sig())
    t = feed(tr, t, 1, lambda t: sig(jaw_open=0.8))  # too short to be a yawn
    t = feed(tr, t, 2, lambda t: sig())
    assert tr.features(t).yawns_240s == 1


def test_stillness_breaks_on_talking():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig())
    assert tr.features(t).stillness_s == pytest.approx(10, abs=0.3)
    t = feed(tr, t, 2, lambda t: sig(mouth_motion=0.1))
    f = tr.features(t)
    assert f.stillness_s == 0
    assert f.mouth_motion_10s > 0.01


def test_stillness_breaks_on_head_motion():
    tr = FeatureTracker()
    t = feed(tr, 0, 6, lambda t: sig())
    t = feed(tr, t, 2, lambda t: sig(head_yaw=(t * 20) % 40))  # turning ~20 deg/s
    f = tr.features(t)
    assert f.stillness_s == 0 and f.head_motion_30s > 0.5


def test_glance_away_count():
    tr = FeatureTracker()
    t = 0.0
    for _ in range(3):  # three 1 s glances away, 4 s apart
        t = feed(tr, t, 3, lambda t: sig())
        t = feed(tr, t, 1, lambda t: sig(gaze_x=0.7))
    t = feed(tr, t, 1, lambda t: sig())
    t = feed(tr, t, 6, lambda t: sig(gaze_x=0.7))  # a long look away is not a glance
    t = feed(tr, t, 1, lambda t: sig())
    assert tr.features(t).glance_away_count_30s == 3


def test_ratios_means_and_emotion():
    tr = FeatureTracker()
    t = feed(tr, 0, 30, lambda t: sig(gaze_x=0.0 if (t % 2) < 1 else 0.7, smile=0.4, cheek_squint=0.3,
                                      brow_down=0.2, mouth_press=0.1, brow_inner_up=0.05,
                                      head_pitch=-8, valence=0.3, arousal=-0.2,
                                      emotion={"neutral": 0.6, "happiness": 0.4}))
    f = tr.features(t)
    assert f.gaze_on_ratio_30s == pytest.approx(0.5, abs=0.05)
    assert f.face_ratio_10s == 1.0
    assert f.smile_10s == pytest.approx(0.4) and f.cheek_squint_10s == pytest.approx(0.3)
    assert f.brow_down_30s == pytest.approx(0.2) and f.mouth_press_30s == pytest.approx(0.1)
    assert f.brow_inner_up_10s == pytest.approx(0.05)
    assert f.head_droop_deg_240s == pytest.approx(-8)
    assert f.valence_30s == pytest.approx(0.3) and f.arousal_30s == pytest.approx(-0.2)
    assert f.emotion_30s["neutral"] == pytest.approx(0.6)
    assert f.observed_s == pytest.approx(30, abs=0.2)


def test_old_frames_drop_out_of_windows():
    tr = FeatureTracker()
    t = feed(tr, 0, 30, lambda t: sig(smile=0.9))
    t = feed(tr, t, 20, lambda t: sig(smile=0.0))
    assert tr.features(t).smile_10s == pytest.approx(0.0)


def test_empty_tracker_features():
    f = FeatureTracker().features(0.0)
    assert f.face_ratio_10s == 0 and f.observed_s == 0 and f.emotion_30s == {}


def test_head_tilt_is_mean_absolute_roll():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig(head_roll=-8 if (t % 2) < 1 else 8))
    assert tr.features(t).head_tilt_10s == pytest.approx(8)



def test_gaze_centred_on_calibrated_screen():
    tr = FeatureTracker()
    tr.set_screen_center(0.0, -0.4, 0.0)  # webcam above the monitor: screen is "down"
    t = feed(tr, 0, 10, lambda t: sig(gaze_y=-0.4))
    assert tr.features(t).gaze_on_ratio_30s == 1.0
    t = feed(tr, t, 5, lambda t: sig(gaze_y=0.2))  # looking up, off the screen
    assert tr.features(t).gaze_away_hold_s == pytest.approx(5, abs=0.3)


def test_gaze_center_from_recent_frames():
    tr = FeatureTracker()
    t = feed(tr, 0, 5, lambda t: sig(gaze_x=0.1, gaze_y=-0.3, head_yaw=4))
    assert tr.gaze_center(t, 5) == pytest.approx((0.1, -0.3, 4.0))


def test_hysteresis_ignores_flicker_near_the_limit():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig(gaze_x=0.33 if int(t * 8) % 2 else 0.37))
    f = tr.features(t)
    assert f.gaze_on_ratio_30s == 1.0 and f.glance_away_count_30s == 0
    assert f.gaze_away_hold_s == 0


def test_short_on_blip_does_not_reset_away_hold():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig(gaze_x=0.7))
    t = feed(tr, t, 0.25, lambda t: sig(gaze_x=0.0))
    t = feed(tr, t, 5, lambda t: sig(gaze_x=0.7))
    assert tr.features(t).gaze_away_hold_s == pytest.approx(15.25, abs=0.3)


def test_short_face_dropout_does_not_reset_away_hold():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig(gaze_x=0.7))
    t = feed(tr, t, 0.25, lambda t: FrameSignals(face=False))
    t = feed(tr, t, 5, lambda t: sig(gaze_x=0.7))
    assert tr.features(t).gaze_away_hold_s == pytest.approx(15, abs=0.4)


def test_tiny_flick_is_not_a_glance():
    tr = FeatureTracker()
    t = feed(tr, 0, 3, lambda t: sig())
    t = feed(tr, t, 0.25, lambda t: sig(gaze_x=0.7))  # 0.25 s: noise, not a glance
    t = feed(tr, t, 3, lambda t: sig())
    assert tr.features(t).glance_away_count_30s == 0


def test_stillness_tolerates_landmark_jitter():
    tr = FeatureTracker()
    t = feed(tr, 0, 10, lambda t: sig(head_yaw=0.5 if int(t * 8) % 2 else 0.0,
                                      head_pitch=0.3 if int(t * 8) % 2 else 0.0,
                                      mouth_motion=0.015))
    assert tr.features(t).stillness_s >= 8


def test_looking_down_is_not_eyes_closing():
    tr = FeatureTracker()
    # Reading the phone: gaze well below the screen, eyelids low (MediaPipe blink rises).
    t = feed(tr, 0, 60, lambda t: sig(gaze_y=-0.7, eye_open=0.1 if (t % 10) < 1.5 else 0.6))
    f = tr.features(t)
    assert f.long_closures_90s == 0 and f.perclos_60s == 0.0
