from moodmusic.mood.groups import MoodGroup, nearest_groups

G = MoodGroup


def test_labels_and_emojis():
    assert G.UPBEAT.label == "Upbeat" and G.UPBEAT.emoji == "😄"
    assert G.CHILL.emoji == "😌"
    assert G.MELANCHOLY.label == "Melancholy" and G.MELANCHOLY.emoji == "😔"
    assert G.INTENSE.emoji == "🔥"
    assert G.FOCUS.emoji == "🎧"
    assert G.UNSORTED.label == "Unsorted" and G.UNSORTED.emoji == "❔"


def test_nearest_groups():
    assert nearest_groups(G.INTENSE)[0] == G.PARTY
    assert nearest_groups(G.MELANCHOLY)[0] == G.PROFOUND
    for g in G:
        near = nearest_groups(g)
        assert g not in near
        assert G.UNSORTED not in near


def test_db_values_unchanged():
    for v in ("focus", "chill", "upbeat", "melancholy", "intense", "unsorted"):
        assert G(v).value == v
    assert G("chill") is G.CHILL


def test_new_groups_labels_emojis():
    assert [g.value for g in G] == ["focus", "profound", "romantic", "chill", "upbeat",
                                    "party", "melancholy", "intense", "unsorted"]
    assert G.PROFOUND.emoji == "🌌" and G.ROMANTIC.emoji == "💞" and G.PARTY.emoji == "🎉"
    assert G.PROFOUND.label == "Profound"


def test_nearest_never_unsorted_and_covers_all():
    real = [g for g in G if g != G.UNSORTED]
    for g in real:
        near = nearest_groups(g)
        assert sorted(near) == sorted(x for x in real if x != g)
        assert len(near) == 7
    assert nearest_groups(G.FOCUS)[:2] == [G.CHILL, G.PROFOUND]
    assert nearest_groups(G.PROFOUND)[0] == G.MELANCHOLY
