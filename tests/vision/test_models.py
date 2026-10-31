from pathlib import Path

from moodmusic.vision import models


class FakeResp:
    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield b"abc"
        yield b"def"


def test_download_then_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "data_dir", lambda: tmp_path)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp()

    monkeypatch.setattr(models.requests, "get", fake_get)
    p = models.face_landmarker_path()
    assert p == tmp_path / "models" / "face_landmarker.task"
    assert p.read_bytes() == b"abcdef"
    assert calls == [models.FACE_LANDMARKER_URL]
    assert not list((tmp_path / "models").glob("*.part"))
    assert models.face_landmarker_path() == p
    assert len(calls) == 1


def test_failed_download_leaves_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "data_dir", lambda: tmp_path)

    class Bad(FakeResp):
        def iter_content(self, chunk_size=1):
            yield b"abc"
            raise IOError("boom")

    monkeypatch.setattr(models.requests, "get", lambda url, **kw: Bad())
    try:
        models.face_landmarker_path()
    except IOError:
        pass
    assert not (tmp_path / "models" / "face_landmarker.task").exists()
    assert not list((tmp_path / "models").glob("*.part"))
