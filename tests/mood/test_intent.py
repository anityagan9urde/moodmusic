import random

from moodmusic.mood.groups import MoodGroup as G
from moodmusic.mood.intent import Intent, Mode, intent_for, is_night
from moodmusic.mood.states import FaceState as F

RNG = random.Random(1)


def test_focus_deep_love_happy_map():
    assert intent_for(F.FOCUSED, Mode.MATCH, 0, 14, RNG).groups == [G.FOCUS]
    assert intent_for(F.DEEP_THOUGHT, Mode.MATCH, 0, 14, RNG).groups == [G.PROFOUND]
    assert intent_for(F.LOVE, Mode.LIFT, 0, 14, RNG).groups == [G.ROMANTIC]
    assert intent_for(F.HAPPY, Mode.MATCH, 0, 14, RNG).groups == [G.UPBEAT]
    excited = intent_for(F.EXCITED, Mode.MATCH, 0, 14, RNG)
    assert excited.groups == [G.PARTY, G.INTENSE] and not excited.lifting


def test_tired_lifts_even_in_match_mode():
    i0 = intent_for(F.TIRED, Mode.MATCH, 0, 14, RNG)
    assert i0.lifting is True and i0.groups == [G.ROMANTIC, G.CHILL]
    assert intent_for(F.TIRED, Mode.MATCH, 1, 14, RNG).groups == [G.CHILL, G.UPBEAT]
    assert intent_for(F.TIRED, Mode.MATCH, 2, 14, RNG).groups == [G.UPBEAT]
    assert intent_for(F.TIRED, Mode.MATCH, 9, 14, RNG).groups == [G.UPBEAT]
    assert i0.note == "lifting you up"


def test_stressed_steps():
    steps = [intent_for(F.STRESSED, Mode.MATCH, n, 14, RNG).groups for n in range(4)]
    assert steps == [[G.CHILL], [G.CHILL, G.UPBEAT], [G.UPBEAT], [G.UPBEAT]]


def test_bored_is_fresh_energetic():
    i = intent_for(F.BORED, Mode.MATCH, 0, 14, RNG)
    assert i == Intent([G.UPBEAT, G.PARTY, G.INTENSE], fresh=True, lifting=True,
                       note="something fresh")


def test_sleepy_day_vs_night():
    day = intent_for(F.SLEEPY, Mode.MATCH, 0, 14, RNG)
    assert day.groups == [G.UPBEAT] and day.note == "waking you up" and day.lifting
    assert intent_for(F.SLEEPY, Mode.MATCH, 1, 14, RNG).groups == [G.PARTY]
    night = intent_for(F.SLEEPY, Mode.MATCH, 0, 22, RNG)
    assert night.groups == [G.CHILL, G.PROFOUND] and night.note == "winding down"
    assert not night.lifting
    assert is_night(5) and not is_night(6) and is_night(21) and not is_night(20)


def test_sad_follows_toggle():
    assert intent_for(F.SAD, Mode.MATCH, 0, 14, RNG).groups == [G.MELANCHOLY]
    lifted = [intent_for(F.SAD, Mode.LIFT, n, 14, RNG) for n in range(3)]
    assert [x.groups for x in lifted] == [[G.CHILL], [G.CHILL, G.UPBEAT], [G.UPBEAT]]
    assert all(x.lifting for x in lifted)


def test_mode_values_unchanged():
    assert Mode("match") is Mode.MATCH and Mode("lift") is Mode.LIFT
