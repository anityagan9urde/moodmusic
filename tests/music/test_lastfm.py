import pytest
import requests

from moodmusic.music.lastfm import LastFmClient, LastFmError, clean_title


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(responses, **kw):
    sleeps = []
    t = {"now": 100.0}
    s = FakeSession(responses)
    c = LastFmClient("KEY", session=s, sleep=sleeps.append, clock=lambda: t["now"], **kw)
    return c, s, sleeps, t


TAGS = {"toptags": {"tag": [{"name": "Chill", "count": "100"}, {"name": "Lo-Fi", "count": 50}]}}


def test_track_tags_parsed():
    c, s, _, _ = make([FakeResp(200, TAGS)])
    assert c.track_tags("A", "B") == [("chill", 100), ("lo-fi", 50)]
    url, p, timeout = s.calls[0]
    assert url == "https://ws.audioscrobbler.com/2.0/"
    assert p["method"] == "track.gettoptags" and p["autocorrect"] == 1
    assert p["format"] == "json" and p["api_key"] == "KEY"
    assert timeout == 10


def test_artist_tags_method():
    c, s, _, _ = make([FakeResp(200, TAGS)])
    c.artist_tags("A")
    assert s.calls[0][1]["method"] == "artist.gettoptags"


def test_single_dict_tag():
    c, _, _, _ = make([FakeResp(200, {"toptags": {"tag": {"name": "Sad", "count": "7"}}})])
    assert c.artist_tags("A") == [("sad", 7)]


def test_rate_limit_sleeps():
    c, _, sleeps, _ = make([FakeResp(200, TAGS), FakeResp(200, TAGS)])
    c.artist_tags("A")
    assert sleeps == []
    c.artist_tags("A")
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(0.25)


def test_429_then_success():
    c, _, sleeps, _ = make([FakeResp(429), FakeResp(200, TAGS)])
    assert c.artist_tags("A")
    assert 1 in sleeps


def test_three_500s_raise_after_backoff():
    c, s, sleeps, _ = make([FakeResp(500)] * 3)
    with pytest.raises(LastFmError):
        c.artist_tags("A")
    assert len(s.calls) == 3
    assert [x for x in sleeps if x >= 1] == [1, 2]


def test_connection_error_retried():
    c, _, _, _ = make([requests.ConnectionError("x"), FakeResp(200, TAGS)])
    assert c.artist_tags("A")


def test_error_6_empty():
    c, s, _, _ = make([FakeResp(200, {"error": 6, "message": "nf"})])
    assert c.track_tags("A", "B") == []
    assert len(s.calls) == 1


def test_error_29_retries():
    c, _, _, _ = make([FakeResp(200, {"error": 29, "message": "rl"}), FakeResp(200, TAGS)])
    assert c.artist_tags("A")


def test_error_10_raises_without_retry():
    c, s, _, _ = make([FakeResp(200, {"error": 10, "message": "bad key"})])
    with pytest.raises(LastFmError):
        c.artist_tags("A")
    assert len(s.calls) == 1


def test_clean_title():
    assert clean_title("Song - Remastered 2011") == "Song"
    assert clean_title("Song (feat. X)") == "Song"
    assert clean_title("Song [feat. X & Y]") == "Song"
    assert clean_title("Song (with X)") == "Song"
    assert clean_title("Song - Radio Edit") == "Song"
    assert clean_title("Song - 2011 Remaster") == "Song"
    assert clean_title("Song - Live at Wembley") == "Song"
    assert clean_title("Plain Song") == "Plain Song"


def test_track_tags_uses_cleaned_title():
    c, s, _, _ = make([FakeResp(200, TAGS)])
    c.track_tags("A", "Song - Remastered 2011")
    assert s.calls[0][1]["track"] == "Song"


def test_connection_error_does_not_leak_api_key():
    url = "https://ws.audioscrobbler.com/2.0/?method=x&api_key=SECRETKEY&format=json"
    errs = [requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")] * 3
    c, _, _, _ = make(errs)
    c.api_key = "SECRETKEY"
    with pytest.raises(LastFmError) as ei:
        c.artist_tags("A")
    assert "SECRETKEY" not in str(ei.value)
    assert "SECRETKEY" not in repr(ei.value)
