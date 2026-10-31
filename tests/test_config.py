import logging

from moodmusic.config import Settings, load_settings, save_settings


def test_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(mode="lift", camera_index=2)
    save_settings(s, p)
    assert load_settings(p) == s


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_corrupt_file_gives_defaults(tmp_path, caplog):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    with caplog.at_level(logging.WARNING):
        assert load_settings(p) == Settings()
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"foo": 1, "camera_index": 3}')
    assert load_settings(p).camera_index == 3


def test_save_is_atomic(tmp_path, monkeypatch):
    import os

    import pytest
    p = tmp_path / "settings.json"
    save_settings(Settings(camera_index=1), p)

    def broken_replace(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        save_settings(Settings(camera_index=2), p)
    assert load_settings(p).camera_index == 1  # old file intact
    assert [f.name for f in tmp_path.iterdir()] == ["settings.json"]  # no temp left behind
    monkeypatch.undo()
    save_settings(Settings(camera_index=3), p)
    assert load_settings(p).camera_index == 3
