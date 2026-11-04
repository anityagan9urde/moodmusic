from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.states import FaceState
from moodmusic.ui.mood_picker import MoodPicker


def test_not_how_i_feel_offers_ten_states(qtbot):
    dlg = MoodPicker(None, "How do you feel?", list(FaceState))
    qtbot.addWidget(dlg)
    assert list(dlg.buttons) == list(FaceState)
    assert dlg.buttons[FaceState.DEEP_THOUGHT].text() == "🤔  Deep in thought"
    dlg.buttons[FaceState.LOVE].click()
    assert dlg.choice == FaceState.LOVE


def test_wrong_vibe_offers_eight_groups(qtbot):
    groups = [g for g in MoodGroup if g != MoodGroup.UNSORTED]
    dlg = MoodPicker(None, "This song fits…", groups)
    qtbot.addWidget(dlg)
    assert len(dlg.buttons) == 8 and MoodGroup.UNSORTED not in dlg.buttons
    assert dlg.buttons[MoodGroup.PROFOUND].text() == "🌌  Profound"
