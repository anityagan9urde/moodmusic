from moodmusic.mood.features import Features
from moodmusic.mood.states import FaceState as F
from moodmusic.mood.tracker import FaceMood, StateTracker

FEAT = Features(valence_30s=0.2, arousal_30s=-0.1, emotion_30s={"neutral": 0.7})


def test_initial_state():
    tr = StateTracker(45)
    assert tr.state == FaceMood()
    assert tr.state.state == F.FOCUSED and tr.state.reason == "" and tr.state.candidate is None


def test_hold_time_required():
    tr = StateTracker(45)
    tr.update((F.FOCUSED, "eyes on the screen"), FEAT, 0.0)
    m = None
    for i in range(1, 90):  # 0.5 s steps: 44.5 s
        m = tr.update((F.HAPPY, "smiling"), FEAT, i * 0.5)
    assert m.state == F.FOCUSED and m.candidate == F.HAPPY
    m = tr.update((F.HAPPY, "smiling"), FEAT, 45.5)
    assert m.state == F.HAPPY and m.since == 45.5 and m.reason == "smiling"
    assert m.valence == 0.2 and m.arousal == -0.1 and m.probs == {"neutral": 0.7}


def test_none_decision_holds_state():
    tr = StateTracker(10)
    tr.update((F.HAPPY, "smiling"), FEAT, 0.0)
    tr.update((F.HAPPY, "smiling"), FEAT, 10.0)  # promoted
    tr.update((F.LOVE, "soft smile"), FEAT, 11.0)  # new candidate
    m = tr.update((None, ""), FEAT, 15.0)  # nothing clear: keep state and candidate timer
    assert m.state == F.HAPPY and m.candidate == F.LOVE
    m = tr.update((F.LOVE, "soft smile"), FEAT, 21.0)
    assert m.state == F.LOVE  # timer from 11.0 kept running


def test_same_state_refreshes_reason():
    tr = StateTracker(10)
    tr.update((F.FOCUSED, "eyes on the screen"), FEAT, 0.0)
    m = tr.update((F.FOCUSED, "head steady, not talking"), FEAT, 1.0)
    assert m.reason == "head steady, not talking" and m.candidate is None


def test_candidate_change_restarts_timer():
    tr = StateTracker(10)
    tr.update((F.HAPPY, "x"), FEAT, 0.0)
    tr.update((F.LOVE, "x"), FEAT, 8.0)
    m = tr.update((F.LOVE, "x"), FEAT, 17.0)
    assert m.state == F.FOCUSED and m.candidate == F.LOVE
    assert tr.update((F.LOVE, "x"), FEAT, 18.0).state == F.LOVE


def test_force_immediate_with_reason():
    tr = StateTracker(45)
    m = tr.force(F.DEEP_THOUGHT, 3.0)
    assert m.state == F.DEEP_THOUGHT and m.since == 3.0 and m.reason == "you said so"
    assert m.candidate is None


def test_set_hold():
    tr = StateTracker(45)
    tr.set_hold(2)
    tr.update((F.HAPPY, "x"), FEAT, 0.0)
    assert tr.update((F.HAPPY, "x"), FEAT, 2.0).state == F.HAPPY


def test_slow_state_needs_sustained_candidacy():
    tr = StateTracker(10)
    tr.update((F.FOCUSED, "x"), FEAT, 0.0)
    for i in range(1, 400):  # Tired decided continuously for 199.5 s
        m = tr.update((F.TIRED, "slow blinks"), FEAT, i * 0.5)
    assert m.state == F.FOCUSED and m.candidate == F.TIRED
    m = tr.update((F.TIRED, "slow blinks"), FEAT, 250.5)  # 240 s window + 10 s hold
    assert m.state == F.TIRED


def test_fast_state_uses_plain_hold():
    tr = StateTracker(10)
    tr.update((F.FOCUSED, "x"), FEAT, 0.0)
    tr.update((F.HAPPY, "x"), FEAT, 1.0)
    assert tr.update((F.HAPPY, "x"), FEAT, 11.0).state == F.HAPPY


def test_force_slow_state_is_immediate():
    assert StateTracker(10).force(F.TIRED, 1.0).state == F.TIRED
