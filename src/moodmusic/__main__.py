import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:  # headless: must not import Qt UI, camera or Spotify
        from moodmusic.selftest import run_selftest
        out = argv[argv.index("--selftest-out") + 1] if "--selftest-out" in argv else None
        return run_selftest(out=out)
    from moodmusic.ui.main import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
