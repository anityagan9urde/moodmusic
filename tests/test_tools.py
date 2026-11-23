from moodmusic.mood.groups import MoodGroup as G
from moodmusic.music.library import Song, SongLibrary
from moodmusic.tools import apply_lines, export_rows, main


def lib_with(tmp_path):
    lib = SongLibrary(tmp_path / "t.db")
    lib.upsert(Song("spotify:track:a", "Zaalima", "Arijit Singh", None, G.UNSORTED))
    lib.upsert(Song("spotify:track:b", "Mercy", "Badshah", None, G.UPBEAT))
    return lib


def test_export_unsorted_only(tmp_path):
    rows = export_rows(lib_with(tmp_path), all_songs=False)
    assert rows == ["spotify:track:a\tZaalima\tArijit Singh\tunsorted"]


def test_export_all(tmp_path):
    rows = export_rows(lib_with(tmp_path), all_songs=True)
    assert sorted(rows) == ["spotify:track:a\tZaalima\tArijit Singh\tunsorted",
                            "spotify:track:b\tMercy\tBadshah\tupbeat"]


def test_apply_sets_override(tmp_path):
    lib = lib_with(tmp_path)
    applied, errors = apply_lines(lib, ["spotify:track:a\tromantic"])
    assert (applied, errors) == (1, [])
    song = lib.get("spotify:track:a")
    assert song.group == G.ROMANTIC and song.override and song.source == "user"


def test_apply_unsorted_clears_override(tmp_path):
    lib = lib_with(tmp_path)
    apply_lines(lib, ["spotify:track:b\tparty"])
    applied, errors = apply_lines(lib, ["spotify:track:b\tunsorted"])
    assert (applied, errors) == (1, [])
    song = lib.get("spotify:track:b")
    assert song.group == G.UNSORTED and not song.override


def test_apply_reports_bad_lines_with_numbers(tmp_path):
    lib = lib_with(tmp_path)
    applied, errors = apply_lines(lib, [
        "# comment", "", "spotify:track:a\tromantic", "spotify:track:zzz\tchill",
        "spotify:track:b\tvibes", "just-one-column"])
    assert applied == 1
    assert errors == ["line 4: unknown song spotify:track:zzz",
                      "line 5: unknown group 'vibes'",
                      "line 6: expected uri<TAB>group"]


def test_apply_accepts_export_format_roundtrip(tmp_path):
    lib = lib_with(tmp_path)
    rows = [r.rsplit("\t", 1)[0] + "\tprofound" for r in export_rows(lib, all_songs=True)]
    applied, errors = apply_lines(lib, rows)
    assert (applied, errors) == (2, [])
    assert {s.group for s in lib.songs()} == {G.PROFOUND}


def test_cli_apply_exit_codes(tmp_path, monkeypatch, capsys):
    lib = lib_with(tmp_path)
    lib.close()
    monkeypatch.setattr("moodmusic.tools.data_dir", lambda: tmp_path)
    (tmp_path / "t.db").rename(tmp_path / "library.db")
    good = tmp_path / "good.tsv"
    good.write_text("spotify:track:a\tchill\n", encoding="utf-8")
    assert main(["apply-sort", str(good)]) == 0
    assert "applied 1, skipped 0" in capsys.readouterr().out
    bad = tmp_path / "bad.tsv"
    bad.write_text("spotify:track:a\tnope\n", encoding="utf-8")
    assert main(["apply-sort", str(bad)]) == 1
    out = tmp_path / "out.tsv"
    assert main(["export-unsorted", "--all", "--out", str(out)]) == 0
    assert "spotify:track:a\tZaalima" in out.read_text(encoding="utf-8")
