# Mood Music

Mood Music looks at your face through your webcam, works out your mood, and plays matching songs from **your own Spotify**. Free, non-commercial, open source.

## Privacy

- Your video **never leaves your computer**. Face analysis runs locally (MediaPipe + an ONNX emotion model).
- **Nothing is recorded or saved**: no frames, no photos. Only the current frame is analysed in memory.
- **No telemetry, no analytics, no accounts.** The only network traffic is to Spotify (play your music), Last.fm (look up song tags, if you add a key) and optionally GitHub (update check, off by default).

## What you need

- **Spotify Premium** (Spotify only allows playback control for Premium accounts).
- A webcam.
- Windows 10/11 or a Mac with Apple Silicon.
- A free Spotify developer app (your own Client ID) and a free Last.fm API key (below).

## Set up your Spotify developer app

1. Go to <https://developer.spotify.com/dashboard> and log in.
2. Click **Create app**. Give it any name and description.
3. Under **Redirect URIs**, add exactly: `http://127.0.0.1:8765/callback` and save.
4. Tick **Web API** (and Web Playback SDK if offered), accept the terms, and save.
5. Open the app's **Settings** and copy the **Client ID**. Paste it into Mood Music's setup wizard. (No client secret is needed.)

## Last.fm API key

Mood Music uses Last.fm tags to sort your songs into moods. Create a free key at <https://www.last.fm/api/account/create> and paste it into the wizard. (If your build already bundles a key, the wizard skips this step.)

## Install

Download the latest build from the Releases page: `MoodMusic-windows.zip` (unzip, run `MoodMusic.exe`) or `MoodMusic-macos-arm64.dmg` (drag to Applications). The builds are **unsigned**, so your OS will warn you the first time.

### Windows: SmartScreen

If you see "Windows protected your PC", click **More info**, then **Run anyway**.

### macOS: unverified developer

Right-click (or Control-click) `MoodMusic.app` and choose **Open**, then **Open** again. Or: try to open it once, then go to **System Settings > Privacy & Security** and click **Open Anyway**. macOS will also ask for **camera permission** the first time. Allow it.

## About "micro-expressions"

Honest note: Mood Music reads **subtle facial expressions and sustained mood** over seconds to minutes, smoothed so music does not jump around. It does **not** detect split-second micro-expressions, and it is not a mind reader. If it guesses wrong, use "Not how I feel" and it learns.

## Run from source

Requires Python 3.12.

```powershell
git clone <this repo>
cd mood-music
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m moodmusic
```

On macOS/Linux use `python3.12 -m venv .venv` and `source .venv/bin/activate`. Run tests with `pytest` (set `QT_QPA_PLATFORM=offscreen` on headless machines).

### Build the app yourself

```powershell
python scripts/fetch_models.py
pyinstaller packaging/moodmusic.spec
dist\MoodMusic\MoodMusic.exe --selftest --selftest-out result.txt
```

`--selftest` loads both models, runs them on a blank frame and prints `SELFTEST OK` (exit code 0) or `SELFTEST FAILED: <reason>` (exit code 1). It never opens the camera, Spotify or a window. Because the Windows exe is windowed and may have no console, `--selftest-out <file>` also writes the result line to a file; CI reads that file.

## Licensing

Mood Music is free and **non-commercial**. The emotion model (HSEmotion, trained on AffectNet) is licensed for non-commercial use only, so do not sell this app or use it commercially. MediaPipe is Apache-2.0. Spotify and Last.fm are trademarks of their owners; this project is not affiliated with them.
