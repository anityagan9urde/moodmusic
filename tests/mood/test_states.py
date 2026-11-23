from moodmusic.mood.states import EVIDENCE_WINDOW_S, FAST_STATES, SLOW_STATES, FaceState as F


def test_labels_and_emojis_complete():
    assert [s.value for s in F] == ["focused", "deep_thought", "love", "tired", "sleepy",
                                    "stressed", "bored", "happy", "excited", "sad"]
    assert [s.label for s in F] == ["Focused", "Deep in thought", "Love / shy", "Tired", "Sleepy",
                                    "Stressed", "Bored", "Happy", "Excited", "Sad"]
    assert [s.emoji for s in F] == ["🧠", "🤔", "🥰", "🥱", "😴", "😣", "😐", "😊", "🤩", "😢"]


def test_fast_and_slow_partition():
    assert FAST_STATES == {F.FOCUSED, F.DEEP_THOUGHT, F.LOVE, F.HAPPY, F.EXCITED, F.SAD}
    assert SLOW_STATES == {F.TIRED, F.SLEEPY, F.STRESSED, F.BORED}
    assert EVIDENCE_WINDOW_S == {F.TIRED: 240, F.BORED: 240, F.SLEEPY: 90, F.STRESSED: 90}
