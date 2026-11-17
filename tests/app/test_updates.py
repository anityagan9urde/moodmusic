import requests

from moodmusic.app import updates


class Resp:
    def __init__(self, payload=None, bad_json=False):
        self._payload, self._bad = payload, bad_json

    def raise_for_status(self):
        pass

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._payload


def patch_get(monkeypatch, resp=None, exc=None):
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw))
        if exc:
            raise exc
        return resp

    monkeypatch.setattr(updates.requests, "get", fake_get)
    return calls


def test_newer_tag_returns_url(monkeypatch):
    calls = patch_get(monkeypatch, Resp({"tag_name": "v0.2.0", "html_url": "https://x/r"}))
    assert updates.check_for_update("0.1.0", "me/repo") == "https://x/r"
    assert calls[0][0] == "https://api.github.com/repos/me/repo/releases/latest"
    assert calls[0][1]["timeout"] == 5


def test_same_tag_returns_none(monkeypatch):
    patch_get(monkeypatch, Resp({"tag_name": "v0.1.0", "html_url": "https://x/r"}))
    assert updates.check_for_update("0.1.0", "me/repo") is None


def test_older_tag_returns_none(monkeypatch):
    patch_get(monkeypatch, Resp({"tag_name": "0.0.9", "html_url": "https://x/r"}))
    assert updates.check_for_update("0.1.0", "me/repo") is None


def test_ten_beats_nine(monkeypatch):
    patch_get(monkeypatch, Resp({"tag_name": "v0.10.0", "html_url": "https://x/r"}))
    assert updates.check_for_update("0.9.0", "me/repo") == "https://x/r"


def test_network_error_returns_none(monkeypatch):
    patch_get(monkeypatch, exc=requests.ConnectionError("down"))
    assert updates.check_for_update("0.1.0", "me/repo") is None


def test_malformed_json_returns_none(monkeypatch):
    patch_get(monkeypatch, Resp(bad_json=True))
    assert updates.check_for_update("0.1.0", "me/repo") is None


def test_missing_fields_or_bad_tag_returns_none(monkeypatch):
    patch_get(monkeypatch, Resp({"tag_name": "nightly", "html_url": "https://x/r"}))
    assert updates.check_for_update("0.1.0", "me/repo") is None
    patch_get(monkeypatch, Resp(["not", "a", "dict"]))
    assert updates.check_for_update("0.1.0", "me/repo") is None


def test_empty_repo_makes_no_network_call(monkeypatch):
    calls = patch_get(monkeypatch, Resp({"tag_name": "v9", "html_url": "u"}))
    assert updates.check_for_update("0.1.0", "") is None
    assert updates.check_for_update("0.1.0") is None  # default UPDATE_REPO is empty
    assert calls == []
