from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.smoother import MoodSmoother
from moodmusic.vision.types import EmotionReading

UP = EmotionReading(probs={"happy": 0.9, "neutral": 0.05}, valence=0.7, arousal=0.6)
FOC = EmotionReading(probs={"neutral": 0.9}, valence=0.0, arousal=0.0)
SAD = EmotionReading(probs={"sad": 0.9, "neutral": 0.05}, valence=-0.7, arousal=-0.6)
ANG = EmotionReading(probs={"angry": 0.9, "neutral": 0.05}, valence=-0.7, arousal=0.6)


def test_initial_state():
    s = MoodSmoother(hold_seconds=45).state
    assert s.group == MoodGroup.FOCUS and s.candidate is None and s.since == 0.0


def test_needs_hold_time():
    sm = MoodSmoother(hold_seconds=45)
    st = None
    for i in range(8 * 40 + 1):
        st = sm.update(UP, i / 8)
    assert st.group == MoodGroup.FOCUS
    assert st.candidate == MoodGroup.UPBEAT
    for i in range(8 * 40 + 1, 8 * 50 + 1):
        st = sm.update(UP, i / 8)
    assert st.group == MoodGroup.UPBEAT
    assert st.candidate is None


def test_brief_frown_ignored():
    sm = MoodSmoother(hold_seconds=45)
    for i in range(8 * 60):
        t = i / 8
        r = SAD if 20 <= t < 23 else FOC
        assert sm.update(r, t).group == MoodGroup.FOCUS


def test_force_switches_immediately():
    sm = MoodSmoother(hold_seconds=45)
    sm.update(FOC, 0.0)
    st = sm.force(MoodGroup.CHILL, 5.0)
    assert st.group == MoodGroup.CHILL and st.since == 5.0 and st.candidate is None
    assert (st.valence, st.arousal) == (0.5, -0.5)
    assert sm.state.group == MoodGroup.CHILL


def test_candidate_reset():
    sm = MoodSmoother(hold_seconds=10, alpha=1.0)
    sm.update(FOC, 0.0)
    assert sm.update(UP, 1.0).candidate == MoodGroup.UPBEAT
    assert sm.update(ANG, 8.0).candidate == MoodGroup.INTENSE
    st = sm.update(ANG, 17.0)  # only 9s since reset
    assert st.group == MoodGroup.FOCUS
    st = sm.update(ANG, 18.0)
    assert st.group == MoodGroup.INTENSE


def test_set_hold():
    sm = MoodSmoother(hold_seconds=100, alpha=1.0)
    sm.update(UP, 0.0)
    sm.set_hold(5)
    assert sm.update(UP, 6.0).group == MoodGroup.UPBEAT
