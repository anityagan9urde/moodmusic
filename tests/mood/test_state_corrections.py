import pytest

from moodmusic.mood.state_corrections import BIAS_CAP, StateCorrections
from moodmusic.mood.states import FaceState as F


def test_no_file_no_bias(tmp_path):
    assert StateCorrections(tmp_path / "sc.jsonl").bias() == {}


def test_bias_accumulates_and_caps(tmp_path):
    c = StateCorrections(tmp_path / "sub" / "sc.jsonl")
    c.record(F.STRESSED, F.FOCUSED)
    b = c.bias()
    assert b[F.FOCUSED] == pytest.approx(0.05) and b[F.STRESSED] == pytest.approx(-0.05)
    for _ in range(20):
        c.record(F.STRESSED, F.FOCUSED)
    b = c.bias()
    assert b[F.FOCUSED] == pytest.approx(BIAS_CAP) and b[F.STRESSED] == pytest.approx(-BIAS_CAP)
    assert StateCorrections(tmp_path / "sub" / "sc.jsonl").bias() == b  # persisted


def test_only_last_50_records_count(tmp_path):
    c = StateCorrections(tmp_path / "sc.jsonl")
    for _ in range(50):
        c.record(F.SAD, F.TIRED)
    for _ in range(50):
        c.record(F.HAPPY, F.LOVE)
    b = c.bias()
    assert F.TIRED not in b and F.SAD not in b
    assert b[F.LOVE] == pytest.approx(BIAS_CAP)


def test_old_corrections_file_ignored(tmp_path):
    (tmp_path / "corrections.jsonl").write_text(
        '{"predicted": "melancholy", "actual": "focus", "valence": -0.3, "arousal": 0}\n')
    assert StateCorrections(tmp_path / "state_corrections.jsonl").bias() == {}


def test_corrupt_lines_skipped(tmp_path):
    p = tmp_path / "sc.jsonl"
    p.write_bytes(b'{"predicted": "sad", "actual": "tired"}\nnot json\n\xff\xfe\n'
                  b'{"predicted": "nope", "actual": "tired"}\n')
    b = StateCorrections(p).bias()
    assert b == {F.SAD: pytest.approx(-0.05), F.TIRED: pytest.approx(0.05)}


def test_same_state_correction_is_noop(tmp_path):
    c = StateCorrections(tmp_path / "sc.jsonl")
    c.record(F.HAPPY, F.HAPPY)
    assert c.bias() == {}
