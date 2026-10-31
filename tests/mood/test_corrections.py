from moodmusic.mood.corrections import CorrectionStore
from moodmusic.mood.groups import MoodGroup


def test_no_corrections_zero_bias(tmp_path):
    assert CorrectionStore(tmp_path / "sub" / "c.jsonl").bias() == (0.0, 0.0)


def test_bias_from_corrections(tmp_path):
    cs = CorrectionStore(tmp_path / "sub" / "c.jsonl")
    for _ in range(5):
        cs.record(MoodGroup.MELANCHOLY, MoodGroup.FOCUS, -0.3, 0.0)
    v, a = cs.bias()
    assert 0 < v <= 0.2
    assert abs(a) < 1e-9


def test_bias_capped(tmp_path):
    cs = CorrectionStore(tmp_path / "c.jsonl")
    cs.record(MoodGroup.MELANCHOLY, MoodGroup.UPBEAT, -0.9, -0.9)
    assert cs.bias() == (0.2, 0.2)


def test_corrupt_lines_skipped_and_persisted(tmp_path):
    p = tmp_path / "c.jsonl"
    cs = CorrectionStore(p)
    cs.record(MoodGroup.MELANCHOLY, MoodGroup.FOCUS, -0.3, 0.0)
    with p.open("a") as f:
        f.write("garbage\n{\"actual\": \"nope\"}\n")
    assert CorrectionStore(p).bias()[0] > 0
