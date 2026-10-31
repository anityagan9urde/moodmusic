from moodmusic.mood.groups import MoodGroup
from moodmusic.music.tags import TAG_KEYWORDS, score_tags


def test_chill():
    assert score_tags([("chill", 100), ("mellow", 80)])[0] == MoodGroup.CHILL


def test_melancholy_beats_chill_keyword():
    assert score_tags([("sad", 100), ("acoustic", 40)])[0] == MoodGroup.MELANCHOLY


def test_genre_only_is_none():
    assert score_tags([("rock", 100), ("pop", 90), ("indie", 80)]) == (None, [])


def test_empty():
    assert score_tags([])[0] is None


def test_case_and_spacing_insensitive():
    group, matched = score_tags([("  Feel   Good ", 60)])
    assert group == MoodGroup.UPBEAT
    assert matched == ["feel good"]


def test_hyphen_and_underscore_as_space():
    assert score_tags([("Rock-Out", 50)])[0] == MoodGroup.INTENSE
    assert score_tags([("feel_good", 50)])[0] == MoodGroup.UPBEAT
    assert score_tags([("lo-fi", 50)])[0] == MoodGroup.FOCUS
    assert score_tags([("lofi", 50)])[0] == MoodGroup.FOCUS


def test_below_threshold_is_none():
    assert score_tags([("happy", 29)])[0] is None
    assert score_tags([("happy", 30)])[0] == MoodGroup.UPBEAT


def test_tie_is_none():
    assert score_tags([("happy", 50), ("sad", 50)])[0] is None


def test_matched_in_input_order():
    _, matched = score_tags([("Mellow", 10), ("rock", 90), ("chill", 80)])
    assert matched == ["mellow", "chill"]


def test_keywords_cover_groups_not_unsorted_or_genres():
    assert MoodGroup.UNSORTED not in TAG_KEYWORDS
    allkw = {k for v in TAG_KEYWORDS.values() for k in v}
    assert not allkw & {"rock", "pop", "indie"}
    assert set(TAG_KEYWORDS) == set(MoodGroup) - {MoodGroup.UNSORTED}


def test_tags_profound_romantic_party():
    assert score_tags([("sufi", 100)])[0] == MoodGroup.PROFOUND
    assert score_tags([("romantic", 80), ("love", 60)])[0] == MoodGroup.ROMANTIC
    assert score_tags([("party", 90)])[0] == MoodGroup.PARTY
