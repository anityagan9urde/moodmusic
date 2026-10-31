from dataclasses import replace

import pytest

from moodmusic.mood.baselines import PersonalBaselines
from moodmusic.mood.features import Features
from moodmusic.mood.rules import Score, decide, score_states
from moodmusic.mood.states import FaceState as F


class WarmBaselines(PersonalBaselines):
    @property
    def warm(self) -> bool:
        return True


WARM, COLD = WarmBaselines(), PersonalBaselines()

# A calm person working: eyes on screen, steady, quiet, neutral face, plenty of history.
AT_DESK = Features(
    face_ratio_10s=1.0, gaze_on_ratio_30s=0.9, gaze_away_hold_s=0.0, head_motion_30s=3.0,
    stillness_s=4.0, mouth_motion_10s=0.005, blink_rate_per_min_60s=15, mean_blink_ms_60s=200,
    perclos_60s=0.05, long_closures_90s=0, yawns_240s=0, head_droop_deg_240s=-5.0,
    head_tilt_10s=1.0, smile_10s=0.05, cheek_squint_10s=0.02, brow_down_30s=0.15,
    brow_inner_up_10s=0.05, mouth_press_30s=0.1, glance_away_count_30s=0, valence_30s=0.0,
    arousal_30s=0.0, emotion_30s={"neutral": 0.8}, observed_s=600.0,
)


def state_of(f: Features, b=WARM, bias=None):
    return decide(score_states(f, b, bias), None)


def test_focused_frown_reads_focused_not_stressed():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.95, brow_down_30s=0.5, stillness_s=12)
    s, reason = state_of(f)
    assert s == F.FOCUSED
    assert "eyes on the screen" in reason
    assert score_states(f, WARM)[F.STRESSED].value < 0.6


def test_looking_away_still_reads_deep_thought():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.1, gaze_away_hold_s=35, stillness_s=30)
    s, reason = state_of(f)
    assert s == F.DEEP_THOUGHT
    assert "looking away" in reason


def test_soft_smile_glance_away_reads_love():
    f = replace(AT_DESK, smile_10s=0.3, glance_away_count_30s=3, head_tilt_10s=9,
                valence_30s=0.3, gaze_on_ratio_30s=0.6)
    assert state_of(f)[0] == F.LOVE


def test_duchenne_smile_reads_happy():
    f = replace(AT_DESK, smile_10s=0.55, cheek_squint_10s=0.35, valence_30s=0.4)
    assert state_of(f)[0] == F.HAPPY


def test_big_smile_energy_reads_excited():
    f = replace(AT_DESK, smile_10s=0.8, cheek_squint_10s=0.4, brow_inner_up_10s=0.4,
                arousal_30s=0.5, valence_30s=0.5, head_motion_30s=12)
    assert state_of(f)[0] == F.EXCITED


def test_slow_heavy_blinks_droop_reads_tired():
    f = replace(AT_DESK, mean_blink_ms_60s=400, perclos_60s=0.25, head_droop_deg_240s=-14,
                arousal_30s=-0.3)
    assert state_of(f)[0] == F.TIRED


def test_yawns_and_closures_read_sleepy():
    f = replace(AT_DESK, long_closures_90s=3, yawns_240s=2, perclos_60s=0.3)
    assert state_of(f)[0] == F.SLEEPY


def test_tension_plus_restless_reads_stressed():
    f = replace(AT_DESK, brow_down_30s=0.4, mouth_press_30s=0.35, head_motion_30s=10,
                valence_30s=-0.3, gaze_on_ratio_30s=0.7)
    assert state_of(f)[0] == F.STRESSED


def test_frown_alone_is_not_stressed():
    f = replace(AT_DESK, brow_down_30s=0.45)
    assert state_of(f)[0] != F.STRESSED
    assert score_states(f, WARM)[F.STRESSED].value == 0.0


def test_wandering_gaze_flat_reads_bored():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.4, glance_away_count_30s=5, yawns_240s=1,
                head_droop_deg_240s=-12, smile_10s=0.03, stillness_s=1)
    assert state_of(f)[0] == F.BORED


def test_talking_on_call_is_not_excited_or_deep_thought():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.8, mouth_motion_10s=0.08, smile_10s=0.3,
                head_motion_30s=5, stillness_s=0, arousal_30s=0.1, valence_30s=0.15)
    assert state_of(f)[0] in (F.FOCUSED, F.HAPPY, None)


def test_weak_single_cue_holds():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.7, gaze_away_hold_s=3)
    assert state_of(f) == (None, "") or state_of(f)[0] == F.FOCUSED
    neutral_away = replace(AT_DESK, gaze_on_ratio_30s=0.5, gaze_away_hold_s=3,
                           brow_down_30s=0.15)
    assert state_of(neutral_away) == (None, "")


def test_warmup_makes_slow_states_harder():
    f = replace(AT_DESK, mean_blink_ms_60s=360, perclos_60s=0.18, head_droop_deg_240s=-12,
                arousal_30s=-0.2)
    assert state_of(f, WARM)[0] == F.TIRED
    assert state_of(f, COLD)[0] != F.TIRED


def test_slow_states_need_their_evidence_window():
    f = replace(AT_DESK, mean_blink_ms_60s=400, perclos_60s=0.25, head_droop_deg_240s=-14,
                arousal_30s=-0.3, observed_s=100)  # under the 240 s Tired window
    assert score_states(f, WARM)[F.TIRED].value == 0.0


def test_sad_reads_sad_unless_explained_by_tiredness():
    sad = replace(AT_DESK, valence_30s=-0.6, arousal_30s=-0.3, gaze_on_ratio_30s=0.5)
    assert state_of(sad)[0] == F.SAD
    tired_and_low = replace(sad, mean_blink_ms_60s=400, perclos_60s=0.25,
                            head_droop_deg_240s=-14)
    assert state_of(tired_and_low)[0] == F.TIRED


def test_bias_tips_close_call():
    f = replace(AT_DESK, smile_10s=0.45, cheek_squint_10s=0.2, valence_30s=0.25)
    scores = score_states(f, WARM)
    assert decide(scores, None)[0] != F.LOVE
    biased = score_states(f, WARM, {F.LOVE: 0.25, F.HAPPY: -0.25})
    assert biased[F.LOVE].value == pytest.approx(min(1.0, scores[F.LOVE].value + 0.25))
    assert decide(biased, None)[0] == F.LOVE


def test_decide_needs_margin_and_threshold():
    s = {st: Score(0.0, []) for st in F}
    s[F.HAPPY], s[F.LOVE] = Score(0.7, ["smiling"]), Score(0.65, ["soft smile"])
    assert decide(s, None) == (None, "")
    s[F.LOVE] = Score(0.5, [])
    assert decide(s, None) == (F.HAPPY, "smiling")
    s[F.HAPPY] = Score(0.55, ["smiling"])
    assert decide(s, F.HAPPY) == (None, "")


def test_focused_frown_with_pressed_lips_and_anger_reads_focused():
    # HSEmotion reads a concentration frown as some anger -> negative valence.
    f = replace(AT_DESK, gaze_on_ratio_30s=0.9, brow_down_30s=0.5, mouth_press_30s=0.3,
                emotion_30s={"anger": 0.5, "neutral": 0.4}, valence_30s=-0.4, stillness_s=12)
    assert state_of(f)[0] == F.FOCUSED
    assert score_states(f, WARM)[F.STRESSED].value < 0.6


def test_stressed_still_detected_when_restless_while_tense():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.9, brow_down_30s=0.4, mouth_press_30s=0.35,
                head_motion_30s=12, valence_30s=-0.4)
    assert state_of(f)[0] == F.STRESSED


def test_call_with_glances_is_not_love():
    f = replace(AT_DESK, gaze_on_ratio_30s=0.8, mouth_motion_10s=0.08, smile_10s=0.3,
                head_motion_30s=5, stillness_s=0, arousal_30s=0.1, valence_30s=0.15,
                glance_away_count_30s=2, head_tilt_10s=4)
    assert state_of(f)[0] in (F.FOCUSED, F.HAPPY, None)
    assert score_states(f, WARM)[F.LOVE].value < 0.6


def test_smile_thresholds_follow_the_users_resting_face():
    smiley = WarmBaselines()
    smiley.calibrate_rest(Features(smile_10s=0.25, gaze_on_ratio_30s=0.85,
                                   brow_down_30s=0.15, mouth_press_30s=0.1,
                                   head_droop_deg_240s=-5, brow_inner_up_10s=0.25,
                                   head_tilt_10s=6))
    resting = replace(AT_DESK, smile_10s=0.3, glance_away_count_30s=2, head_tilt_10s=7,
                      valence_30s=0.2, brow_inner_up_10s=0.25)
    assert state_of(resting, smiley)[0] != F.LOVE  # that's just this person's resting face
    assert state_of(resting, WARM)[0] == F.LOVE  # for a typical face it's a soft smile
    assert score_states(resting, smiley)[F.STRESSED].value == 0.0


def test_heavy_eyelids_alone_are_not_sleepy():
    f = replace(AT_DESK, long_closures_90s=3, perclos_60s=0.3, yawns_240s=0)
    assert state_of(f)[0] != F.SLEEPY
    nodding = replace(f, head_droop_deg_240s=-15)
    assert state_of(nodding)[0] == F.SLEEPY
