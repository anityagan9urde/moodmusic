from pathlib import Path

import pytest

from moodmusic.vision import models


@pytest.fixture(autouse=True)
def no_bundled_copy(monkeypatch):
    """A fetched model in src/moodmusic/resources must not change download behaviour."""
    monkeypatch.setattr(models, "resource_path", lambda name: None)


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


def test_bundled_copy_preferred(monkeypatch, tmp_path):
    bundled = tmp_path / "face_landmarker.task"
    bundled.write_bytes(b"x")
    monkeypatch.setattr(models, "resource_path", lambda name: bundled if name == "face_landmarker.task" else None)
    monkeypatch.setattr(models.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("net")))
    assert models.face_landmarker_path() == bundled


def test_resource_path_frozen(monkeypatch, tmp_path):
    from moodmusic import resources
    d = tmp_path / "moodmusic" / "resources"
    d.mkdir(parents=True)
    (d / "a.txt").write_text("k")
    monkeypatch.setattr(resources.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resources.resource_path("a.txt") == d / "a.txt"
    assert resources.resource_path("nope.txt") is None
