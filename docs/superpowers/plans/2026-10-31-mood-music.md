# Mood Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A desktop app that reads the user's mood from their webcam locally and plays matching (or mood-lifting) songs from their own Spotify playlist.

**Architecture:** A Python package `moodmusic` with these parts:
- **Logic layers** with no UI or network inside, all unit-tested:
  - `vision` turns camera frames into face and emotion readings.
  - `mood` turns readings into a stable mood group.
  - `music` sorts songs into mood groups and picks songs.
  - `spotify` handles login and playback.
- **`Engine`** wires them together and is tested with fakes.
- **PySide6 UI** (widget, dashboard, setup wizard, settings, review) is a thin layer over `Engine`. A worker thread runs camera → mood, and Qt signals carry state to the UI.

**Tech Stack:**
- Python 3.12
- `mediapipe` (FaceLandmarker), `hsemotion-onnx` + `onnxruntime`, `opencv-python`
- `PySide6`, `spotipy` (PKCE), `requests`, `keyring`, `platformdirs`
- `pytest`, `pytest-qt`, PyInstaller, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-10-31-mood-music-design.md`

## Global Constraints

- Python **3.12** (`py -3.12`). 3.14 is installed but MediaPipe has no wheels for it.
- No frames or face images ever written to disk or sent over the network. Only numbers (baseline, corrections) persist.
- Network calls only to Spotify and Last.fm (plus the GitHub releases check in Task 15).
- Five mood groups, exactly: `UPBEAT`, `CHILL`, `MELANCHOLY`, `INTENSE`, `FOCUS`. Plus `UNSORTED` for songs only.
- Modes: `MATCH`, `LIFT`. Lift steps: Melancholy→Chill→Upbeat, Intense→Chill, Chill→Chill (occasional Upbeat), Upbeat→Upbeat, Focus→Focus.
- Defaults:
  - hold time 45 s, with sensitivity presets Relaxed 90 s / Normal 45 s / Responsive 20 s
  - away-pause 10 min
  - mid-song behaviour = wait for song end
  - calibration 20 s
  - analysis 8 fps
- Spotify: PKCE, Client ID only, redirect `http://127.0.0.1:8765/callback`. Scopes: `user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative user-library-read user-read-private`.
- Tokens are stored in the OS keyring (service name `moodmusic`). Settings, cache and logs go under `platformdirs.user_data_dir("MoodMusic")`.
- Mood history is in memory only, current session.
- Every network or camera failure becomes a visible status message, never a crash or silent stop.

## Review Focus

1. **Resting face looks sad or angry.** A user whose neutral face scores negative valence must read as `FOCUS` after calibration. Test in Task 4.
2. **No active Spotify device / Spotify closed.** `play()` must raise `NoActiveDevice` and the engine must surface "Open Spotify on any device", not crash. Tests in Tasks 9 and 11.
3. **A mood group has zero songs** (e.g. no Intense songs in the library). The selector falls back to the nearest group and says so in the reason. Test in Task 8.
4. **Playlist contains local files, podcasts, or removed tracks** (`track` is `None`, `is_local` true, `type` = `episode`). They are skipped during sync. Test in Task 9.
5. **Token expiry or network drop mid-session.** Spotify calls retry once after refresh and on connection errors, then raise `SpotifyUnavailable`. The engine keeps running and retries later. Tests in Tasks 9 and 11.

---

## File Structure

```
pyproject.toml                      deps, pytest config, entry point
README.md                           install, Spotify/Last.fm key setup, unsigned-app warnings
src/moodmusic/
  __init__.py
  __main__.py                       python -m moodmusic → ui.main.run()
  config.py                         Settings dataclass + load/save, paths
  logging_setup.py                  rotating file log
  vision/
    types.py                        FaceObservation, EmotionReading, QualityReport
    camera.py                       CameraSource (reconnecting OpenCV capture)
    face.py                         FaceTracker (MediaPipe FaceLandmarker)
    emotion.py                      EmotionModel protocol + HSEmotionModel
    quality.py                      assess_quality()
    models.py                       model file download/locate
  mood/
    groups.py                       MoodGroup, Mode, classify(), lift_target(), nearest_groups()
    calibration.py                  Baseline, Calibrator
    smoother.py                     MoodSmoother, MoodState
    corrections.py                  CorrectionStore
  music/
    tags.py                         TAG_KEYWORDS, score_tags()
    lastfm.py                       LastFmClient
    library.py                      Song, SongLibrary (SQLite)
    scanner.py                      Scanner
    selector.py                     SongSelector, Pick
  spotify/
    auth.py                         make_auth_manager(), KeyringCacheHandler
    client.py                       SpotifyService + exceptions
  app/
    engine.py                       Engine (mood → music orchestration)
    worker.py                       VisionWorker (QThread: camera→face→emotion→smoother)
    updates.py                      check_for_update()
  ui/
    main.py                         QApplication bootstrap, tray, window switching
    widget.py                       simple floating widget (mockup A)
    dashboard.py                    advanced dashboard (mockup B)
    wizard.py                       first-run setup
    settings_dialog.py
    review_dialog.py                song group review / drag between groups
    mood_picker.py                  "not how I feel" / "wrong vibe" chooser
tests/                              mirrors src layout
packaging/moodmusic.spec            PyInstaller spec
.github/workflows/build.yml         Windows + macOS builds and tests
```

---

### Task 1: Project skeleton, settings and logging

**Files:**
- Create: `pyproject.toml`, `src/moodmusic/__init__.py`, `src/moodmusic/__main__.py`, `src/moodmusic/config.py`, `src/moodmusic/logging_setup.py`, `tests/test_config.py`, update `.gitignore` (add `.venv/`, `__pycache__/`, `dist/`, `build/`, `src/moodmusic/resources/lastfm_key.txt`)

**Interfaces:**
- Produces:
  - `Settings` dataclass with fields:
    - `spotify_client_id: str = ""`, `lastfm_api_key: str = ""`
    - `source_playlist_id: str | None = None` (`None` = Liked Songs)
    - `camera_index: int = 0`
    - `sensitivity: str = "normal"`
    - `switch_mode: str = "wait"` (`"wait"` or `"immediate"`)
    - `away_pause_minutes: int = 10` (0 = off)
    - `mode: str = "match"`
    - `view: str = "simple"`
    - `start_at_login: bool = False`
    - `setup_complete: bool = False`
  - `load_settings(path: Path | None = None) -> Settings`
  - `save_settings(s: Settings, path: Path | None = None) -> None`
  - `data_dir() -> Path`
  - `HOLD_SECONDS = {"relaxed": 90, "normal": 45, "responsive": 20}`
  - `setup_logging() -> Path`

- [ ] **Step 1:** Create a venv: `py -3.12 -m venv .venv` and `.venv\Scripts\pip install -e .[dev]`. The pyproject lists the Tech Stack deps, plus the dev extras `pytest pytest-qt pyinstaller`. pytest uses `pythonpath = ["src"]`.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
  - `test_roundtrip`: save `Settings(mode="lift", camera_index=2)` to `tmp_path/"s.json"`, load it, and check it is equal.
  - `test_missing_file_gives_defaults`: loading from a nonexistent path gives `Settings()`.
  - `test_corrupt_file_gives_defaults`: a file containing `{not json` loads as `Settings()` and logs a warning; it does not raise.
  - `test_unknown_keys_ignored`: a JSON file with an extra `"foo":1` still loads.
- [ ] **Step 3:** Run `.venv\Scripts\pytest tests/test_config.py -v`. Expected: FAIL (import error).
- [ ] **Step 4:** Implement `config.py` and `logging_setup.py`:
  - `data_dir` = `platformdirs.user_data_dir("MoodMusic")`, created if missing.
  - The log is a `RotatingFileHandler` at `data_dir/"moodmusic.log"`, 1 MB × 3.
  - `__main__` calls `moodmusic.ui.main.run()`, which is stubbed for now.
- [ ] **Step 5:** Run the tests. Expected: PASS.
- [ ] **Step 6:** Commit: `feat: project skeleton, settings, logging`.

### Task 2: Mood groups, classification and lift logic

**Files:** Create `src/moodmusic/mood/__init__.py`, `src/moodmusic/mood/groups.py`, `tests/mood/test_groups.py`

**Interfaces:**
- Produces:
  - `class MoodGroup(str, Enum)` with values `UPBEAT CHILL MELANCHOLY INTENSE FOCUS UNSORTED`, and `.label`/`.emoji` properties (😄 😌 😔 😤 🎧 ❔).
  - `class Mode(str, Enum)`: `MATCH`, `LIFT`.
  - `classify(valence: float, arousal: float, neutral_prob: float) -> MoodGroup`
  - `lift_target(current: MoodGroup, rng: random.Random) -> MoodGroup`
  - `target_group(current: MoodGroup, mode: Mode, rng: random.Random) -> MoodGroup`
  - `nearest_groups(g: MoodGroup) -> list[MoodGroup]`: fallback order, excluding `g`.

- [ ] **Step 1: Write failing tests:**
  - `classify(0.5, 0.5, 0.1) == UPBEAT`
  - `classify(0.4, -0.3, 0.1) == CHILL`
  - `classify(-0.5, -0.3, 0.1) == MELANCHOLY`
  - `classify(-0.5, 0.5, 0.1) == INTENSE`
  - `classify(0.05, 0.05, 0.2) == FOCUS` (inside the neutral zone)
  - `classify(0.5, 0.5, 0.7) == FOCUS` (`neutral_prob >= 0.6` wins)
  - `lift_target(MELANCHOLY) == CHILL`
  - `lift_target(INTENSE) == CHILL`
  - `lift_target(UPBEAT) == UPBEAT`
  - `lift_target(FOCUS) == FOCUS`
  - `lift_target(CHILL)` over 1000 draws with `Random(1)` is `UPBEAT` between 10% and 30% of the time, otherwise `CHILL`
  - `target_group(MELANCHOLY, MATCH) == MELANCHOLY`
  - `nearest_groups(INTENSE)[0] == UPBEAT` (same energy)
  - `nearest_groups(MELANCHOLY)[0] == CHILL`
  - `UNSORTED` is never returned by `nearest_groups`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Neutral zone: `abs(valence) < 0.15 and abs(arousal) < 0.15`.
  - Outside the zone, the quadrant is chosen by the signs of valence and arousal.
  - Lift from CHILL picks `UPBEAT` with probability 0.2.
  - Lift from Melancholy goes one step at a time: each re-evaluation moves it one step. The engine re-targets after each song (Task 11).
  - `nearest_groups` order:
    - UPBEAT→[CHILL, INTENSE, FOCUS, MELANCHOLY]
    - CHILL→[FOCUS, UPBEAT, MELANCHOLY, INTENSE]
    - MELANCHOLY→[CHILL, FOCUS, INTENSE, UPBEAT]
    - INTENSE→[UPBEAT, FOCUS, CHILL, MELANCHOLY]
    - FOCUS→[CHILL, UPBEAT, MELANCHOLY, INTENSE]
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: mood groups, classification, lift logic`.

### Task 3: Vision types and emotion model wrapper

**Files:** Create `src/moodmusic/vision/__init__.py`, `vision/types.py`, `vision/emotion.py`, `vision/models.py`, `tests/vision/test_emotion.py`

**Interfaces:**
- Produces:
  - `EmotionReading(probs: dict[str, float], valence: float, arousal: float)` (frozen dataclass). `probs` keys are lowercase: `anger contempt disgust fear happiness neutral sadness surprise`.
  - `class EmotionModel(Protocol): def predict(self, face_rgb: np.ndarray) -> EmotionReading`
  - `HSEmotionModel(model_name="enet_b0_8_va_mtl")`
  - `FaceObservation(face_count: int, bbox: tuple[int,int,int,int] | None, blendshapes: dict[str,float], landmarks: np.ndarray | None)`
  - `QualityReport(ok: bool, issue: str | None)`
  - `models.face_landmarker_path() -> Path`: downloads `face_landmarker.task` from the official MediaPipe models URL into `data_dir()/models` on first use. On later runs it uses the cached copy.

- [ ] **Step 1: Write failing tests:**
  - `test_hsemotion_maps_output`: monkeypatch the underlying `HSEmotionRecognizer.predict_emotions` to return `(["Happiness"], np.array([[0,0,0,0,0.9,0.1,0,0, 0.6, 0.3]]))` (8 logits followed by valence and arousal). `predict(np.zeros((224,224,3),np.uint8))` should give `probs["happiness"]` as the max, `valence == pytest.approx(0.6)` and `arousal == pytest.approx(0.3)`. The probs sum to 1 after softmax.
  - `test_valence_clamped`: an output valence of 1.7 is clamped to 1.0.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement using `hsemotion_onnx.facial_emotions.HSEmotionRecognizer(model_name=...)` with `predict_emotions(img, logits=True)`. Apply softmax to the first 8 values; the last two are valence/arousal. Check the package's class order at implementation time and map it to the lowercase keys. Keep all HSEmotion imports inside `emotion.py`, because the spec requires the model to be swappable.
- [ ] **Step 4:** Run. Expected: PASS. Then run a manual smoke test (not in CI): a script in `scripts/smoke_emotion.py` loads the real model on a blank image without error.
- [ ] **Step 5:** Commit: `feat: emotion model wrapper (swappable)`.

### Task 4: Calibration

**Files:** Create `mood/calibration.py`, `tests/mood/test_calibration.py`

**Interfaces:**
- Consumes: `EmotionReading`.
- Produces:
  - `Baseline(valence: float, arousal: float, neutral_prob_scale: float)` with `to_dict()/from_dict()`.
  - `Calibrator(duration_s: float = 20.0)` with:
    - `.add(reading: EmotionReading, t: float)`
    - `.progress -> float` (0..1)
    - `.done -> bool`
    - `.result() -> Baseline` (raises `ValueError` if fewer than 20 samples)
  - `apply_baseline(r: EmotionReading, b: Baseline) -> EmotionReading`
  - `load_baseline() -> Baseline | None`, `save_baseline(b) -> None` (JSON in `data_dir`).

- [ ] **Step 1: Write failing tests:**
  - `test_resting_sad_face_becomes_neutral` (Review Focus 1):
    1. Feed 100 readings with valence -0.35, arousal -0.1, neutral 0.3 over 20 s.
    2. Apply the baseline to a reading with the same values.
    3. Check `classify(r.valence, r.arousal, r.probs["neutral"]) == MoodGroup.FOCUS`.
  - `test_real_smile_still_upbeat`: with the same baseline, a reading at valence 0.4, arousal 0.3 classifies as UPBEAT.
  - `test_too_few_samples_raises`.
  - `test_progress`: 10 s into a 20 s calibration gives `progress == 0.5`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - Use the median of valence and arousal as the baseline.
  - `apply_baseline` subtracts the baseline and clamps the result to [-1, 1].
  - `neutral_prob_scale` = `0.6 / max(median_neutral, 0.1)`. Applying it multiplies the neutral prob by this scale, capped at 1, so a person whose resting neutral prob is low still reaches the 0.6 neutral threshold at rest.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: personal neutral-face calibration`.

### Task 5: Smoothing, hold time, corrections

**Files:** Create `mood/smoother.py`, `mood/corrections.py`, `tests/mood/test_smoother.py`, `tests/mood/test_corrections.py`

**Interfaces:**
- Produces:
  - `MoodState(group: MoodGroup, since: float, valence: float, arousal: float, probs: dict[str,float], candidate: MoodGroup | None)`. `candidate` is the group currently building up but not yet held long enough.
  - `MoodSmoother(hold_seconds: float, alpha: float = 0.15)` with:
    - `.update(r: EmotionReading, t: float) -> MoodState`
    - `.force(group: MoodGroup, t: float) -> MoodState` (used by "not how I feel")
    - `.state`
    - `.set_hold(seconds)`
  - `CorrectionStore(path: Path)` with:
    - `.record(predicted: MoodGroup, actual: MoodGroup, valence: float, arousal: float)`
    - `.bias() -> tuple[float, float]`: a valence/arousal offset learned from corrections, capped at ±0.2.

- [ ] **Step 1: Write failing tests:**
  - `test_needs_hold_time`: starting in FOCUS, feed UPBEAT-level readings at 8 Hz with `hold_seconds=45`. At t=40 the group is still FOCUS (with `candidate == UPBEAT`). At t=50 the group is UPBEAT.
  - `test_brief_frown_ignored` (spec anti-goal 5): a 3 s spike of MELANCHOLY readings in a stream of FOCUS readings never changes the group.
  - `test_force_switches_immediately`.
  - `test_candidate_reset`: if the candidate changes, the hold timer restarts.
  - `test_bias_from_corrections`: record 5 corrections where predicted is MELANCHOLY and actual is FOCUS at valence -0.3. The bias valence is positive and ≤ 0.2.
  - `test_no_corrections_zero_bias`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - The smoother applies an EMA to valence, arousal and probs, then classifies.
  - The group changes only after the candidate has held for `hold_seconds`.
  - `bias()` is the mean of (target-centre − observed) over the last 50 corrections, times 0.5, clamped. The target centres are UPBEAT (0.5,0.5), CHILL (0.5,-0.5), MELANCHOLY (-0.5,-0.5), INTENSE (-0.5,0.5) and FOCUS (0,0).
  - Corrections persist as JSON lines.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: mood smoothing with hold time and corrections`.

### Task 6: Face tracking, quality check, camera

**Files:** Create `vision/face.py`, `vision/quality.py`, `vision/camera.py`, `tests/vision/test_quality.py`, `tests/vision/test_camera.py`

**Interfaces:**
- Produces:
  - `FaceTracker()` with `.process(frame_bgr: np.ndarray, timestamp_ms: int) -> FaceObservation` (MediaPipe FaceLandmarker in VIDEO mode, `num_faces=2`, `output_face_blendshapes=True`), plus `.close()`.
  - `crop_face(frame_bgr, bbox, margin=0.2) -> np.ndarray` (RGB).
  - `assess_quality(frame_bgr: np.ndarray, obs: FaceObservation) -> QualityReport`, which returns one of these issue strings exactly:
    - `"No face visible"`
    - `"More than one face. Point the camera at just you"`
    - `"Too dark. Add some light"`
    - `"Strong light behind you"`
    - `"Face too small. Move closer"`
    - `"Turn to face the camera"`
    - `"Camera looks blocked"`
  - `CameraSource(index: int)` with `.read() -> np.ndarray | None` (`None` while reconnecting) and `.status -> str` (`"ok" | "reconnecting" | "unavailable"`), plus `.release()`. After 3 consecutive failed reads it releases and retries opening every 2 s.
  - `list_cameras(max_index=5) -> list[int]`.

- [ ] **Step 1: Write failing tests:**
  - Quality, with synthetic frames:
    - black frame with no face → `"Camera looks blocked"`
    - mid-grey frame with no face → `"No face visible"`
    - `face_count=2` → the multiple-faces message
    - a frame with mean brightness 25 and a face → `"Too dark. Add some light"`
    - a bright background (230) with a dark face box (60) → `"Strong light behind you"`
    - a face bbox under 8% of frame width → `"Face too small. Move closer"`
    - a good frame → `ok=True, issue=None`
  - Camera: monkeypatch `cv2.VideoCapture` with a fake that fails 3 reads and then succeeds. Check that `status` goes `ok → reconnecting → ok` and that `read()` never raises.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - Head turn comes from landmark x-asymmetry (the nose tip relative to the eye corners). "Turn to face the camera" fires when the yaw proxy is over 0.35.
  - On Windows, open the camera with the `cv2.CAP_DSHOW` backend.
- [ ] **Step 4:** Run. Expected: PASS. Manual check: `scripts/smoke_face.py` opens the webcam and prints the quality and top blendshapes for 5 s.
- [ ] **Step 5:** Commit: `feat: face tracking, quality checks, reconnecting camera`.

### Task 7: Tag scoring and Last.fm client

**Files:** Create `music/__init__.py`, `music/tags.py`, `music/lastfm.py`, `tests/music/test_tags.py`, `tests/music/test_lastfm.py`

**Interfaces:**
- Produces:
  - `TAG_KEYWORDS: dict[MoodGroup, list[str]]`, seeded from the spec's table plus synonyms.
  - `score_tags(tags: list[tuple[str, int]]) -> tuple[MoodGroup | None, list[str]]`: the input is `(tag, weight 0..100)`. The output is the best group (or `None` if the best score is under 30 or there's a tie), plus the matched tags for the reason text.
  - `LastFmClient(api_key: str, session: requests.Session | None = None, min_interval: float = 0.25)` with:
    - `.track_tags(artist: str, title: str) -> list[tuple[str,int]]`
    - `.artist_tags(artist: str) -> list[tuple[str,int]]`
  - Raises `LastFmError` after 3 retries with backoff (on 429, 5xx and connection errors). Last.fm error 6 ("not found") returns `[]`.

- [ ] **Step 1: Write failing tests:**
  - `score_tags([("chill",100),("mellow",80)])[0] == CHILL`
  - `score_tags([("sad",100),("acoustic",40)])[0] == MELANCHOLY`
  - `score_tags([("rock",100)])[0] is None` (genre only, not a mood)
  - `score_tags([])[0] is None`
  - Matching is case- and spacing-insensitive (`"Feel Good"` matches `"feel good"`).
  - Last.fm, with a fake session:
    - a 200 response with `toptags.tag` gives a list of tuples
    - the 2nd call within `min_interval` sleeps (patch `time.sleep` and assert it was called)
    - a 429 followed by 200 succeeds
    - three 500s raise `LastFmError`
    - `{"error":6}` gives `[]`
    - the title is cleaned with `clean_title("Song - Remastered 2011")` → `"Song"` and `clean_title("Song (feat. X)")` → `"Song"`, so lookups hit
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement against `https://ws.audioscrobbler.com/2.0/` with `method=track.gettoptags` / `artist.gettoptags`, `autocorrect=1` and `format=json`. Scoring sums the weights of matching keywords per group.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: Last.fm tags and mood scoring`.

### Task 8: Song library cache and selector

**Files:** Create `music/library.py`, `music/selector.py`, `tests/music/test_library.py`, `tests/music/test_selector.py`

**Interfaces:**
- Produces:
  - `Song(uri: str, title: str, artist: str, album_art: str | None, group: MoodGroup, tags: list[str], source: str, override: bool)`. `source` is one of `"track" | "artist" | "user" | "none"`.
  - `SongLibrary(db_path: Path)` (SQLite) with:
    - `.upsert(song)`, `.get(uri)`
    - `.set_group(uri, group, by_user=True)`
    - `.songs(group=None) -> list[Song]`
    - `.uris() -> set[str]`, `.remove(uris: set[str])`
    - `.counts() -> dict[MoodGroup,int]`
  - A user override is never replaced by a rescan.
  - `Pick(song: Song, group: MoodGroup, reason: str, fell_back_from: MoodGroup | None)`
  - `SongSelector(library, rng: random.Random)` with:
    - `.pick(target: MoodGroup, mood: MoodState) -> Pick | None` (`None` only if the library has no sorted songs at all)
    - `.mark_played(uri)`

- [ ] **Step 1: Write failing tests:**
  - Library: upsert/get roundtrip; `set_group` sets `override=True`; upserting a scanned result over an overridden song keeps the user's group; `counts` and `remove` work; the database survives reopening.
  - `test_no_repeat_until_most_played`: with 10 CHILL songs, 8 consecutive picks are all distinct.
  - `test_empty_group_falls_back` (Review Focus 3): with no INTENSE songs and some UPBEAT songs, `pick(INTENSE)` gives an UPBEAT song with `fell_back_from=INTENSE`, and the reason contains `"no Intense songs"`.
  - `test_unsorted_never_picked`.
  - `test_reason_text`: the reason for a CHILL pick with tags `["mellow","acoustic"]` contains `"Chill"`, `"mellow"` and `"acoustic"`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. No-repeat uses an in-memory recent-played deque per group, sized `max(1, int(0.8 * group_size))`. Reason format:
  `"{Group}: you look {mood words}; tagged {tag1}, {tag2}"`
  or `"…; sorted by artist style"`, with `" (no {Target} songs yet)"` appended on fallback.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: song library cache and selector`.

### Task 9: Spotify auth and service

**Files:** Create `spotify/__init__.py`, `spotify/auth.py`, `spotify/client.py`, `tests/spotify/test_client.py`

**Interfaces:**
- Produces:
  - `make_auth_manager(client_id: str) -> spotipy.SpotifyPKCE`, using the Global Constraints redirect and scopes, `open_browser=True`, and a `KeyringCacheHandler` that stores tokens in `keyring`.
  - Exceptions: `SpotifyError`, `NotPremium(SpotifyError)`, `NoActiveDevice(SpotifyError)`, `SpotifyUnavailable(SpotifyError)`.
  - `PlaybackInfo(uri: str | None, progress_ms: int, duration_ms: int, is_playing: bool, device_id: str | None)`
  - `Device(id, name, type, is_active)`
  - `SpotifyService(sp: spotipy.Spotify)` with:
    - `.check_premium()` (raises `NotPremium`)
    - `.playlists() -> list[tuple[id, name, count]]`
    - `.iter_source_tracks(playlist_id: str | None) -> Iterator[tuple[uri, title, artist, art_url]]` (`None` = Liked Songs; paginated)
    - `.devices() -> list[Device]`
    - `.playback() -> PlaybackInfo | None`
    - `.play(uri, device_id=None)`, `.queue(uri)`, `.pause()`, `.resume()`, `.next()`, `.previous()`
  - Every call goes through `_call(fn, *a)`: on `SpotifyException` 401 it retries once (spotipy refreshes the token); on 404 "NO_ACTIVE_DEVICE" or the "Player command failed: No active device" reason it raises `NoActiveDevice`; on 403 premium-required it raises `NotPremium`; on 429 it sleeps `Retry-After` (capped at 10 s) and retries once; on `requests.ConnectionError` or 5xx it raises `SpotifyUnavailable`.

- [ ] **Step 1: Write failing tests** with a fake `sp` object:
  - `test_iter_skips_local_episodes_and_none` (Review Focus 4): two pages of items. One has `track: None`, one has `is_local: True`, one has `type: "episode"`. Only the 2 valid tracks are yielded, and the second page is fetched via `sp.next`.
  - `test_no_active_device_raises` (Review Focus 2): `start_playback` raises `SpotifyException(404, -1, "Player command failed: No active device found", reason="NO_ACTIVE_DEVICE")`, so the call raises `NoActiveDevice`.
  - `test_401_retries_once_then_succeeds` (Review Focus 5).
  - `test_connection_error_raises_unavailable` (Review Focus 5).
  - `test_not_premium`: `me()` returns `product: "free"`, so `check_premium()` raises `NotPremium`.
  - `test_keyring_cache_roundtrip` with an in-memory keyring backend.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Liked Songs uses `current_user_saved_tracks(limit=50)`; playlists use `playlist_items(..., additional_types=("track",))`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: Spotify PKCE auth and resilient service wrapper`.

### Task 10: Library scanner

**Files:** Create `music/scanner.py`, `tests/music/test_scanner.py`

**Interfaces:**
- Consumes: `SpotifyService.iter_source_tracks`, `LastFmClient`, `score_tags`, `SongLibrary`.
- Produces:
  - `ScanProgress(done: int, total: int, current: str)`
  - `Scanner(service, lastfm, library)` with `.run(playlist_id: str | None, on_progress: Callable[[ScanProgress], None], should_stop: Callable[[], bool]) -> ScanProgress`
  - Behaviour:
    - Fetch the playlist track list.
    - Remove songs from the library that are no longer in the source.
    - Scan only URIs not already in the library.
    - For each one, try track tags first, then artist tags (an artist-tag cache is kept in memory per run), then fall back to `UNSORTED`.
    - On a `LastFmError` for one song, skip it (it stays unscanned and is retried on the next run) and continue.
  - `suggest_group(song, library) -> MoodGroup | None`: the most common group among the same artist's sorted songs.

- [ ] **Step 1: Write failing tests** with fakes:
  - `test_scans_only_new`: a library with 2 songs and a source with 3 songs makes exactly 1 Last.fm call.
  - `test_removes_missing`.
  - `test_artist_fallback_sets_source_artist`.
  - `test_unsorted_when_no_tags`.
  - `test_lastfm_error_skips_song_and_continues`.
  - `test_stop_flag_halts`.
  - `test_progress_callback_called_per_song`.
  - `test_suggest_group_by_artist`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: incremental background library scanner`.

### Task 11: Engine (mood → music orchestration)

**Files:** Create `app/__init__.py`, `app/engine.py`, `tests/app/test_engine.py`

**Interfaces:**
- Consumes: `MoodState`, `target_group`, `SongSelector`, `SpotifyService`, `Settings`.
- Produces:
  - `EngineStatus(kind: str, message: str)`, where `kind` is `"ok" | "warning" | "error"`.
  - `Engine(service, selector, settings, clock: Callable[[], float], rng)` with:
    - `.on_mood(state: MoodState)`
    - `.on_quality(report: QualityReport)`
    - `.on_face_present(present: bool)`
    - `.tick()` (called every 2 s)
    - `.set_mode(Mode)`, `.set_enabled(bool)`
    - `.skip()`, `.toggle_pause()`, `.previous()`
    - `.wrong_vibe(new_group: MoodGroup)`
    - `.not_how_i_feel(group: MoodGroup)`, which delegates to a smoother callback passed in as `force_mood: Callable[[MoodGroup], None]`
    - `.current_pick -> Pick | None`
    - `.status -> EngineStatus`
    - `.history -> list[tuple[float, float, float]]`: (t, valence, arousal), last 60 min, in memory only.
    - Listeners: `.listeners: list[Callable[[], None]]`, called on any change.
- Rules:
  - **Starting playback:** when enabled and the mood group's target differs from what's playing, choose a song:
    - In `switch_mode="immediate"`: `play` now.
    - In `"wait"`: `queue` the song once and wait for the current song to end. Track this with `playback()` in `tick` (when `uri` changes, or `progress_ms > duration_ms - 3000`).
  - **When a song ends:** mark it played, pick the next song from the *current* target, and play it. In Lift mode, re-target on each song so Melancholy→Chill→Upbeat advances one step per song.
  - **Manual control:** if `playback().uri` is neither our pick nor our queued song, the user chose something manually. Don't auto-pick until that song ends.
  - **Poor quality or no face:** no music changes. The status shows the quality issue as a `warning`.
  - **Away:** if there has been no face for `away_pause_minutes` (and that setting isn't 0), pause. When the face returns, resume.
  - **Spotify errors:**
    - `NoActiveDevice` → error status `"Open Spotify on any device"`.
    - `SpotifyUnavailable` → warning status `"Can't reach Spotify. Retrying…"`, retried on the next tick.
    - `NotPremium` → error status `"Spotify Premium is needed for playback control"`.
  - The engine never raises out of public methods. Unexpected exceptions are logged and turned into an error status.

- [ ] **Step 1: Write failing tests** with a `FakeService` that records calls and is scriptable to raise, plus a fake clock:
  - `test_wait_mode_queues_not_plays`
  - `test_immediate_mode_plays`
  - `test_lift_mode_steps_one_group_per_song` (MELANCHOLY mood → first pick CHILL; after the song ends, still MELANCHOLY mood → CHILL again; mood CHILL → CHILL/UPBEAT)
  - `test_manual_song_backs_off`
  - `test_poor_quality_freezes_music`
  - `test_away_pauses_then_resumes`
  - `test_no_active_device_status_and_no_crash` (Review Focus 2)
  - `test_unavailable_retries_next_tick` (Review Focus 5)
  - `test_wrong_vibe_moves_song_and_skips_if_mismatch`
  - `test_disabled_does_nothing`
  - `test_history_trimmed_to_60_minutes`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite (`pytest -q`). Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: engine orchestrating mood to music`.

### Task 12: Vision worker thread

**Files:** Create `app/worker.py`, `tests/app/test_worker.py`

**Interfaces:**
- Consumes: `CameraSource`, `FaceTracker`, `crop_face`, `assess_quality`, `EmotionModel`, `apply_baseline`, `CorrectionStore.bias`, `MoodSmoother`.
- Produces:
  - `VisionWorker(QThread)`, constructed with `(camera_factory, tracker_factory, model_factory, baseline: Baseline | None, smoother, corrections, fps=8)`.
  - Signals:
    - `mood = Signal(object)` (MoodState)
    - `quality = Signal(object)` (QualityReport)
    - `face_present = Signal(bool)`
    - `reading = Signal(object)` (EmotionReading, raw for the dashboard bars)
    - `preview = Signal(object)`: an annotated QImage, emitted only when `preview_enabled` is True (dashboard open)
    - `camera_status = Signal(str)`
    - `calibration_progress = Signal(float)`
    - `calibration_done = Signal(object)` (Baseline)
  - Methods: `.start_calibration()`, `.set_preview(bool)`, `.force_mood(group)` (thread-safe via a queue), `.stop()`.
  - The loop throttles to `fps`. Any exception inside one iteration is logged and the loop continues; after 20 consecutive errors it emits `camera_status("unavailable")` and sleeps 2 s.

- [ ] **Step 1: Write failing tests** with `pytest-qt` and fakes (a camera returning a fixed frame, a tracker returning one face, a model returning a fixed reading):
  - `test_emits_mood_and_quality`
  - `test_calibration_emits_progress_and_baseline` (with a fast fake clock, `duration_s=0.5`)
  - `test_exception_in_model_does_not_kill_thread`
  - `test_no_preview_when_disabled`
  - `test_stop_joins_within_2s`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. The preview draws the face bbox and a sparse landmark mesh with OpenCV and converts to QImage in memory only.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: vision worker thread`.

### Task 13: UI: widget, dashboard, mood picker, tray, app bootstrap

**Files:** Create `ui/__init__.py`, `ui/main.py`, `ui/widget.py`, `ui/dashboard.py`, `ui/mood_picker.py`, `tests/ui/test_widget.py`, `tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `Engine`, `VisionWorker` signals, `Settings`.
- Produces:
  - `MoodWidget(engine, worker)`, matching mockup A in `docs/superpowers/specs/assets/2026-10-31-layout-mockups.html`:
    - frameless, `Qt.WindowStaysOnTopHint`, draggable, about 280×130
    - shows the emoji + mood label, "steady for N min", album art, title/artist, and ⏮ ⏸ ⏭
    - a Match/Lift toggle, a "Not how I feel" button, a "Wrong vibe" button, and a status dot (green/amber/red, tooltip = status message)
    - an "Advanced ⤢" button
  - `Dashboard(engine, worker)`, matching mockup B:
    - camera preview with mesh
    - 8 emotion bars
    - a positive/energy line chart over session history (QPainter, no extra chart dependency)
    - now playing + "picked because…"
    - Match/Lift toggle, status line, and Settings / Review songs / Simple view buttons
  - `MoodPicker.ask(parent, title) -> MoodGroup | None`: five buttons with emoji and label.
  - `run()` in `ui/main.py`:
    1. Load settings and set up logging.
    2. If `not setup_complete`, run the wizard (Task 14).
    3. Otherwise build the service, library, selector, engine and worker.
    4. Show the view from `settings.view`, with a `QSystemTrayIcon` menu: Show, Pause auto-pick, Simple/Advanced, Settings, Quit.
    5. Closing a window hides it to the tray. A `QTimer` calls `engine.tick()` every 2 s.
    6. Install `sys.excepthook` to log and show a non-fatal error toast.

- [ ] **Step 1: Write failing tests** with `pytest-qt` and a fake engine:
  - `test_widget_shows_mood_and_song` (labels update when listeners fire)
  - `test_widget_status_dot_colors`
  - `test_mode_toggle_calls_engine`
  - `test_wrong_vibe_opens_picker_and_calls_engine` (monkeypatch `MoodPicker.ask`)
  - `test_dashboard_enables_preview_on_show_and_disables_on_hide`
  - `test_switch_views_persists_setting`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Styling: dark, rounded, as in the mockups.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: simple widget, advanced dashboard, tray`.

### Task 14: First-run wizard, settings dialog, song review

**Files:** Create `ui/wizard.py`, `ui/settings_dialog.py`, `ui/review_dialog.py`, `tests/ui/test_wizard.py`, `tests/ui/test_review.py`

**Interfaces:**
- Consumes: `Settings`, `make_auth_manager`, `SpotifyService`, `LastFmClient`, `VisionWorker` (calibration), `Scanner`, `SongLibrary`, `suggest_group`.
- Produces:
  - `SetupWizard(QWizard)` with pages in the spec's order:
    1. **Welcome / privacy:** copy states that video never leaves the computer and nothing is recorded.
    2. **Spotify key:** numbered instructions — open developer.spotify.com/dashboard → Create app → set the redirect URI to `http://127.0.0.1:8765/callback` (with a copy button) → tick Web API → paste the Client ID. A "Log in to Spotify" button runs the PKCE flow on a thread, then `check_premium()`; `NotPremium` shows a clear message and blocks Next.
    3. **Last.fm key:** skipped if a bundled `resources/lastfm_key.txt` exists. Otherwise it gives instructions plus a paste box and validates with one `artist_tags("Radiohead")` call.
    4. **Camera:** camera picker, live preview, and the quality message. Next is enabled once the quality is ok.
    5. **Calibration:** "Relax and look at the screen", with a progress bar for 20 s. The baseline is saved.
    6. **Source:** choose Liked Songs or a playlist (from `playlists()`). Finishing starts the scan in a background `QThread` and opens the widget.
  - `SettingsDialog(settings)`: every setting from spec §5 Settings, plus "Open log file" and "Log out of Spotify" (clears the keyring).
  - `ReviewDialog(library)`:
    - six lists (the five groups + Unsorted) with drag-and-drop between them, which calls `library.set_group(by_user=True)`
    - Unsorted items show "Suggested: X" from `suggest_group`, with a one-click accept
    - scan progress shown at the top while scanning

- [ ] **Step 1: Write failing tests:**
  - `test_spotify_page_blocks_next_until_logged_in`
  - `test_not_premium_shows_message`
  - `test_lastfm_page_skipped_when_bundled_key`
  - `test_finish_sets_setup_complete_and_saves`
  - `test_review_drag_sets_override` (simulated by calling the drop handler)
  - `test_unsorted_accept_suggestion`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5: Manual end-to-end on Windows**, with the user's Spotify and Last.fm keys:
  1. `python -m moodmusic` and complete the wizard.
  2. Confirm a song plays.
  3. Smile and hold it for 45 s: the mood becomes Upbeat.
  4. Test wrong vibe, then "not how I feel".
  5. Unplug the webcam: the status shows and recovers.
  6. Close Spotify: "Open Spotify on any device" appears.
- [ ] **Step 6:** Commit: `feat: setup wizard, settings, song review`.

### Task 15: Update check, packaging, CI, README

**Files:** Create `app/updates.py`, `tests/app/test_updates.py`, `packaging/moodmusic.spec`, `.github/workflows/build.yml`, `README.md`

**Interfaces:**
- Produces:
  - `check_for_update(current: str, repo: str = "OWNER/mood-music") -> str | None`: returns the release URL if the GitHub latest release tag is newer. Any error returns `None`.
  - Called once at startup on a thread. If a URL comes back, the tray shows "Update available".

- [ ] **Step 1: Write failing tests:**
  - newer tag → URL
  - same tag → `None`
  - network error → `None`
  - malformed JSON → `None`
- [ ] **Step 2:** Run. Expected: FAIL. Implement it, run again. Expected: PASS.
- [ ] **Step 3: Write the PyInstaller spec:**
  - windowed, one-dir
  - bundles mediapipe data files (`collect_data_files("mediapipe")`), the hsemotion onnx model, and an app icon
  - macOS: `info_plist` with `NSCameraUsageDescription = "Mood Music reads your expression locally to choose music. Video never leaves your computer."`
  - Build locally: `.venv\Scripts\pyinstaller packaging/moodmusic.spec`. Expected: `dist/MoodMusic/MoodMusic.exe` launches to the wizard.
- [ ] **Step 4:** Pre-download models at build time so the first run works offline for vision. Bundle `face_landmarker.task`; `models.face_landmarker_path()` prefers the bundled copy.
- [ ] **Step 5: Write the GitHub Actions workflow** with a matrix of `windows-latest` and `macos-14` (Apple Silicon). Steps:
  1. setup-python 3.12
  2. `pip install -e .[dev]`
  3. `pytest -q` (Qt offscreen: `QT_QPA_PLATFORM=offscreen`)
  4. pyinstaller
  5. On macOS, `hdiutil create` a `.dmg`
  6. Upload artifacts
  7. On tag push, attach them to a GitHub Release
  - The macOS smoke job runs `MoodMusic.app/Contents/MacOS/MoodMusic --selftest`.
- [ ] **Step 6: Add a `--selftest` CLI flag** in `__main__.py`. It loads both models on a blank frame, prints `SELFTEST OK`, and exits 0. Test: `test_selftest_flag` runs it with fake models and asserts the exit code is 0.
- [ ] **Step 7: Write the README.** Cover:
  - what it does and the privacy promise
  - requirements (Spotify Premium)
  - setting up the Spotify developer app (with the redirect URI)
  - the Last.fm key
  - getting past the Windows SmartScreen and macOS "unverified developer" warnings (right-click → Open; System Settings → Privacy & Security → Open Anyway)
  - the micro-expressions honesty note
  - running from source
- [ ] **Step 8:** Run the full suite plus the packaged `--selftest` on Windows. Expected: `SELFTEST OK`.
- [ ] **Step 9:** Commit: `feat: update check, packaging, CI, README`.

---

## Spec coverage check

| Spec item | Task |
|---|---|
| MediaPipe + HSEmotion local, no frames saved | 3, 6, 12 |
| Calibration, recalibrate | 4, 14 (settings) |
| Quality messages, freeze music on poor quality | 6, 11 |
| "Not how I feel", learning | 5, 11, 13 |
| Smoothing / hold time / sensitivity | 5, 1 |
| Away pause | 11 |
| Five groups, Match/Lift, stepwise lift | 2, 11 |
| Last.fm tags → artist fallback → Unsorted, suggest | 7, 10 |
| Background, incremental scan, cached | 10, 14 |
| Review screen, wrong vibe override | 8, 13, 14 |
| Reason text | 8, 13 |
| Device handling, no-repeat, wait vs immediate, manual backoff, on/off | 9, 8, 11 |
| Wizard steps, Premium check, settings list | 14 |
| Widget A, Dashboard B, tray/menu bar | 13 |
| Reliability: camera, Spotify, Last.fm, crash safety, log | 6, 9, 10, 11, 12, 13 |
| Session-only history, keyring tokens, no telemetry | 11, 9 |
| Windows first, macOS via CI, unsigned + instructions | 15 |
| Update-available notice | 15 |
| Swappable emotion model | 3 |
