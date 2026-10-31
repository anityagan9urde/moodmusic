import random

from moodmusic.mood.groups import (
    Mode,
    MoodGroup,
    classify,
    lift_target,
    nearest_groups,
    target_group,
)

G = MoodGroup


def test_labels_and_emojis():
    assert G.UPBEAT.label == "Upbeat" and G.UPBEAT.emoji == "😄"
    assert G.CHILL.emoji == "😌"
    assert G.MELANCHOLY.label == "Melancholy" and G.MELANCHOLY.emoji == "😔"
    assert G.INTENSE.emoji == "😤"
    assert G.FOCUS.emoji == "🎧"
    assert G.UNSORTED.label == "Unsorted" and G.UNSORTED.emoji == "❔"


def test_classify_quadrants():
    assert classify(0.5, 0.5, 0.1) == G.UPBEAT
    assert classify(0.4, -0.3, 0.1) == G.CHILL
    assert classify(-0.5, -0.3, 0.1) == G.MELANCHOLY
    assert classify(-0.5, 0.5, 0.1) == G.INTENSE


def test_classify_neutral_zone_and_neutral_prob():
    assert classify(0.05, 0.05, 0.2) == G.FOCUS
    assert classify(0.5, 0.5, 0.7) == G.FOCUS
    assert classify(0.5, 0.5, 0.6) == G.FOCUS


def test_lift_deterministic_cases():
    rng = random.Random()
    assert lift_target(G.MELANCHOLY, rng) == G.CHILL
    assert lift_target(G.INTENSE, rng) == G.CHILL
    assert lift_target(G.UPBEAT, rng) == G.UPBEAT
    assert lift_target(G.FOCUS, rng) == G.FOCUS


def test_lift_from_chill_is_sometimes_upbeat():
    rng = random.Random(1)
    results = [lift_target(G.CHILL, rng) for _ in range(1000)]
    upbeat = results.count(G.UPBEAT)
    assert 100 <= upbeat <= 300
    assert upbeat + results.count(G.CHILL) == 1000


def test_target_group_modes():
    rng = random.Random()
    assert target_group(G.MELANCHOLY, Mode.MATCH, rng) == G.MELANCHOLY
    assert target_group(G.MELANCHOLY, Mode.LIFT, rng) == G.CHILL
    assert target_group(G.UNSORTED, Mode.MATCH, rng) == G.FOCUS


def test_nearest_groups():
    assert nearest_groups(G.INTENSE)[0] == G.UPBEAT
    assert nearest_groups(G.MELANCHOLY)[0] == G.CHILL
    for g in G:
        near = nearest_groups(g)
        assert g not in near
        assert G.UNSORTED not in near
