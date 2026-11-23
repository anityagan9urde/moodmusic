# Mood States Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-emotion mood with ten explainable face states (nine plus Sad), inferred from several facial signals over time against the user's own baseline, and drive eight song groups from them.

**Architecture:** The vision worker turns each frame into numeric `FrameSignals` (blendshapes, gaze, head pose, plus emotion). A `FeatureTracker` keeps rolling-window `Features`. `score_states()` applies explainable rules against `PersonalBaselines` plus per-state correction bias. A `StateTracker` applies hold time and produces `MoodState(state, reason, …)`. The engine maps each state to a music `Intent` (song groups, lift step, fresh flag), and the selector picks from eight song groups using a persistent play history.

**Tech Stack:** Python 3.12, MediaPipe FaceLandmarker (blendshapes + landmarks), HSEmotion ONNX, PySide6, SQLite, pytest / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-10-31-mood-states-design.md` (builds on `docs/superpowers/specs/2026-10-31-mood-music-design.md`)

## Global Constraints

- **Face states:** exactly `FOCUSED, DEEP_THOUGHT, LOVE, TIRED, SLEEPY, STRESSED, BORED, HAPPY, EXCITED, SAD`. Labels:
  - Focused, Deep in thought, Love / shy, Tired, Sleepy, Stressed, Bored, Happy, Excited, Sad.
- **Song groups:** exactly `FOCUS, PROFOUND, ROMANTIC, CHILL, UPBEAT, PARTY, MELANCHOLY, INTENSE`, plus `UNSORTED`.
  - Enum values are lowercase names, so the existing DB values `focus, chill, upbeat, melancholy, intense, unsorted` stay valid with no migration.
  - "Fresh" is a selection rule, not a group.
- **State → music** (user decisions):
  - Focused → Focus
  - Deep in thought → Profound
  - Love/shy → Romantic
  - Happy → Upbeat
  - Excited → Party (mixed with Intense)
  - Tired → lift: Romantic/Chill → Upbeat
  - Stressed → lift: Chill → Upbeat
  - Bored → Fresh (Upbeat, Party, Intense; least recently played first)
  - Sleepy → wake-up (Upbeat → Party) by day, wind-down (Chill/Profound) at night
  - Sad → Melancholy in Match mode, lift toward Chill → Upbeat in Lift mode
- **Lift rules:** Tired, Stressed and Bored always lift, even in Match mode. Lifting advances one step per song and resets when the state changes.
- **Night:** 21:00–06:00 local time. It is decided only when the next song is chosen, never mid-song.
- **Holds:**
  - Fast states (Focused, Deep in thought, Love, Happy, Excited, Sad) use the existing `HOLD_SECONDS` presets.
  - Slow states need sustained evidence first: Tired and Bored over a 240 s window, Sleepy and Stressed over a 90 s window. The hold then applies on top.
- **Warm-up:** until 30 minutes of baseline data exist, slow states need stronger evidence (their thresholds are multiplied by 1.5).
- **Corrections:** a per-state bias, capped at ±0.25 score, persisted as numbers in `data_dir()/"state_corrections.jsonl"`. The old `corrections.jsonl` is ignored and never read.
- **Privacy:** no frames are written to disk. Baselines, corrections and play history persist as numbers or URIs only. The signal recorder writes numbers only.
- **Sort file format:** one line per song, `uri<TAB>group`. Group names are lowercase enum values. `unsorted` clears an override.
- **Explainability:** every state carries a short reason string built from the features that drove it, e.g. "looking away 40 s, very still".
- Analysis stays at 8 fps, and per-frame work stays cheap arithmetic.

## Switch-over note

Tasks 1–7 are additive (new modules alongside the old pipeline). Tasks 8–10 switch the worker, engine and UI over; between Task 8 and Task 10 the test suite stays green but the running app is only fully consistent again after Task 10. Don't hand the app to the user mid-switch.

## Review Focus

1. **Talking on a call** (mouth moving, eyes on screen, sometimes smiling) must not read as Excited or Deep in thought. Its most likely reading is Focused or Happy. Test in Task 6.
2. **Face lost because the head is turned too far** must not count as gaze-away evidence for Deep in thought. Absence is absence, and the away-pause behaviour stays as it was. Test in Task 4.
3. **Empty song groups:** the user's library may have no Focus, Party or Profound songs. Fallback must follow intent order, and the reason must say so. Test in Task 2.
4. **Weak or contradictory signals** (glasses glare, dim light, one cue only): no state change; the current state holds. Test in Tasks 6 and 7.
5. **Clock crossing 21:00 mid-song** must not switch music. The day/night decision is only used when choosing the next song. Test in Task 3.

---

## File Structure

```
src/moodmusic/
  mood/
    states.py          NEW  FaceState enum (+label, emoji), FAST/SLOW sets, evidence windows
    groups.py          MOD  MoodGroup = song groups (8 + UNSORTED), nearest_groups(); classify/lift/GROUP_CENTRES removed
    intent.py          NEW  Intent, intent_for(state, mode, step, hour, rng)
    features.py        NEW  FeatureTracker -> Features (rolling windows)
    baselines.py       NEW  PersonalBaselines (calibration + passive rolling medians, persisted)
    rules.py           NEW  score_states(features, baselines, bias) -> {FaceState: Score}; decide()
    tracker.py         NEW  FaceMood(state, since, reason, valence, arousal, probs, candidate); StateTracker
    state_corrections.py NEW per-state bias store (state_corrections.jsonl)
    smoother.py, corrections.py  DELETED in Task 10 (old five-label pipeline)
  vision/
    signals.py         NEW  FrameSignals + extract_signals(obs, reading)
  music/
    tags.py            MOD  TAG_KEYWORDS for 8 groups
    library.py         MOD  play_history table: record_play(uri, t), last_played() -> dict[uri, t]
    selector.py        MOD  pick(intent, mood) with Fresh ordering and intent-ordered fallback; reasons use state labels
  app/
    worker.py          MOD  signals -> FeatureTracker -> rules -> StateTracker; emits mood + features
    engine.py          MOD  state -> Intent; lift step per state; handled-state instead of handled-group
  ui/
    mood_picker.py     MOD  ask_state() (10 states) and ask_group() (8 groups)
    widget.py          MOD  state emoji+label, reason tooltip
    dashboard.py       MOD  signals panel + state timeline
    review_dialog.py   MOD  8 groups + Unsorted
  tools.py             NEW  python -m moodmusic.tools export-unsorted | apply-sort <file>
scripts/record_signals.py  NEW  spike: prompts + CSV of FrameSignals (numbers only)
```

---

### Task 1: Frame signals + recording spike tool

**Files:** Create `src/moodmusic/vision/signals.py`, `scripts/record_signals.py`, `tests/vision/test_signals.py`

**Interfaces:**
- Consumes: `FaceObservation(face_count, bbox, blendshapes: dict[str,float], landmarks: np.ndarray | None)` (478 normalized landmarks, x/y/z) and `EmotionReading`.
- Produces a frozen dataclass `FrameSignals` with these fields (all floats unless noted):
  - `face`: bool
  - `gaze_x`, `gaze_y`: −1..1. Iris position relative to the eye corners, combined with `eyeLook*` blendshapes. Positive means right or up.
  - `gaze_on_screen`: bool, true when |gaze_x| < 0.35, |gaze_y| < 0.35 and |head_yaw| < 25°.
  - `head_yaw`, `head_pitch`, `head_roll`: degrees, from landmarks.
  - `eye_open`: 0..1, mean of 1 − eyeBlinkLeft/Right.
  - `smile`: mean of mouthSmileLeft/Right.
  - `cheek_squint`: mean of cheekSquintLeft/Right. This is the Duchenne cue.
  - `brow_down`: mean of browDownLeft/Right.
  - `brow_inner_up`
  - `mouth_press`: mean of mouthPressLeft/Right.
  - `jaw_open`
  - `mouth_motion`: |Δ jawOpen| + |Δ mouthClose| versus the previous frame. Use 0 on the first frame.
  - `valence`, `arousal`
  - `emotion`: dict[str, float]
- Produces `extract_signals(obs: FaceObservation, reading: EmotionReading | None, prev: FrameSignals | None) -> FrameSignals`. With no face it returns `FrameSignals(face=False, …zeros)`.

- [ ] **Step 1: Write failing tests** in `tests/vision/test_signals.py`, using synthetic landmarks and blendshapes built by a helper `make_obs(yaw_deg=0, iris_dx=0, blend={})`:
  - `test_no_face_returns_face_false`
  - `test_frontal_face_gaze_on_screen`: yaw 0, iris centred → `gaze_on_screen is True` and `abs(head_yaw) < 5`.
  - `test_iris_shift_left_reads_gaze_away`: iris at 70% toward the outer corner → `gaze_on_screen is False` and `gaze_x < -0.35`.
  - `test_head_turn_30deg_reads_off_screen`
  - `test_smile_and_cheek_from_blendshapes`: `{"mouthSmileLeft":.8,"mouthSmileRight":.6,"cheekSquintLeft":.4,"cheekSquintRight":.4}` → `smile == approx(.7)` and `cheek_squint == approx(.4)`.
  - `test_eye_open_from_blinks`: blinks .9/.9 → `eye_open == approx(.1)`.
  - `test_mouth_motion_uses_previous_frame`
- [ ] **Step 2:** Run `.venv/Scripts/pytest tests/vision/test_signals.py -v`. Expected: FAIL, import error.
- [ ] **Step 3: Implement `signals.py`.**
  - Head pose from landmarks: yaw comes from the nose-tip x offset relative to the outer eye corners (1, 33, 263), normalized and mapped to degrees with `asin`. Pitch comes from the nose-tip y relative to the eye line and chin (152). Roll comes from the angle of the eye line.
  - Iris centres are landmarks 468 (left) and 473 (right). Use eye corners 33/133 and 362/263.
- [ ] **Step 4: Write `scripts/record_signals.py`** (manual and interactive, not run in CI).
  - It opens the configured camera via `CameraSource`, `FaceTracker` and `HSEmotionModel`.
  - It prompts in the console through timed segments: "look at the screen 15 s", "look left/away 15 s", "look up thinking 15 s", "blink normally 15 s", "yawn twice", "smile 10 s", "frown while reading 15 s", "talk as if on a call 15 s".
  - It writes `signals-<timestamp>.csv` (numbers plus a segment label only, never images) to the current directory and prints per-segment means of `gaze_on_screen`, `gaze_x`, `head_yaw`, `eye_open`, `jaw_open`, `brow_down`, `smile` and `mouth_motion`.
- [ ] **Step 5:** Run the tests. Expected: PASS. Run the full suite. Expected: PASS.
- [ ] **Step 6:** Commit with message `feat: per-frame face signals and signal recorder spike tool`.

> **Checkpoint (controller, with the user):** the user runs `scripts/record_signals.py` once at their desk. The controller reads the printed segment means.
> - **Gate:** "screen" and "away" segments must separate on `gaze_on_screen` with at least 80% vs 20% of frames.
> - If gaze does not separate, the controller ledgers a ruling that Deep in thought and Love/shy use head pose plus stillness only. Task 6 receives that ruling.
> - The measured means also seed the default thresholds in Task 6.

### Task 2: Eight song groups, play history, Fresh-aware selector

**Files:** Modify `src/moodmusic/mood/groups.py`, `src/moodmusic/music/tags.py`, `src/moodmusic/music/library.py`, `src/moodmusic/music/selector.py`. Tests: `tests/mood/test_groups.py`, `tests/music/test_tags.py`, `tests/music/test_library.py`, `tests/music/test_selector.py`.

**Interfaces:**
- **`MoodGroup`:**
  - Members `FOCUS, PROFOUND, ROMANTIC, CHILL, UPBEAT, PARTY, MELANCHOLY, INTENSE, UNSORTED`, with lowercase values.
  - `.label`
  - `.emoji`: 🎧 🌌 💞 😌 😄 🎉 😔 🔥 ❔
  - Remove `classify`, `lift_target`, `target_group`, `GROUP_CENTRES` and `Mode` from this module. `Mode` moves to `intent.py` in Task 3. Update imports in later tasks only. This task keeps old callers compiling by leaving `Mode` re-exported until Task 3.
- **`nearest_groups(g) -> list[MoodGroup]`:** intent-ordered fallback, never including UNSORTED:
  - FOCUS: CHILL, PROFOUND, ROMANTIC, UPBEAT, MELANCHOLY, PARTY, INTENSE
  - PROFOUND: MELANCHOLY, CHILL, FOCUS, ROMANTIC, UPBEAT, INTENSE, PARTY
  - ROMANTIC: CHILL, PROFOUND, UPBEAT, MELANCHOLY, FOCUS, PARTY, INTENSE
  - CHILL: ROMANTIC, FOCUS, PROFOUND, UPBEAT, MELANCHOLY, PARTY, INTENSE
  - UPBEAT: PARTY, ROMANTIC, CHILL, INTENSE, FOCUS, PROFOUND, MELANCHOLY
  - PARTY: UPBEAT, INTENSE, ROMANTIC, CHILL, FOCUS, PROFOUND, MELANCHOLY
  - MELANCHOLY: PROFOUND, CHILL, ROMANTIC, FOCUS, UPBEAT, INTENSE, PARTY
  - INTENSE: PARTY, UPBEAT, FOCUS, CHILL, PROFOUND, ROMANTIC, MELANCHOLY
- **`TAG_KEYWORDS`:** add keywords for the new groups:
  - PROFOUND: deep, introspective, reflective, sufi, soulful, philosophical, spiritual, ghazal
  - ROMANTIC: love, romantic, love songs, romance, ballad
  - PARTY: party, club, dance, edm, bhangra, banger
  - UPBEAT: drop "party" and "dance" (they move to PARTY); keep happy, feel good, upbeat, fun, summer
- **`SongLibrary`:** new table `play_history(uri TEXT PRIMARY KEY, last_played REAL)` created if missing. Add `record_play(uri: str, t: float) -> None` and `last_played() -> dict[str, float]`.
- **`SongSelector.pick(groups: list[MoodGroup], mood, fresh: bool = False, now: float = 0.0) -> Pick | None`:**
  - Try each group in order, then `nearest_groups(groups[0])`.
  - With `fresh`, pool all songs from `groups` and choose randomly among the 25% least recently played (never-played songs first).
  - `mark_played(uri, now)` also calls `library.record_play`.
  - `Pick` gains `groups: list[MoodGroup]`.
  - Reason format: `"{Group}: you seem {state label lowercase}; tagged a, b"`. On fallback, append `" (no {Target} songs yet)"`. With fresh, use `"; something you haven't heard in a while"`.
  - Until Task 10, the selector accepts either the old `MoodState` (use `.group.label`) or the new `FaceMood` (use `.state.label`). Tests use stubs.

- [ ] **Step 1: Write failing tests.**
  - `test_db_values_unchanged`: `MoodGroup("chill") is MoodGroup.CHILL`, and the same for focus, upbeat, melancholy, intense and unsorted.
  - `test_nearest_never_unsorted_and_covers_all`: every group's fallback lists the other 7 exactly once.
  - `test_tags_profound_romantic_party`: `score_tags([("sufi",100)])[0] == PROFOUND`, `[("romantic",80),("love",60)] → ROMANTIC`, `[("party",90)] → PARTY`.
  - `test_play_history_roundtrip`
  - `test_empty_focus_falls_back_to_chill` (Review Focus 3): the library has only CHILL and UPBEAT songs. `pick([FOCUS], mood)` returns a CHILL song with `fell_back_from == FOCUS`, and the reason contains `"no Focus songs yet"`.
  - `test_fresh_prefers_never_played`: of 8 UPBEAT/PARTY songs, 6 have recent history and 2 have none. Over 20 picks with `fresh=True`, the result is always one of those 2.
  - `test_pick_groups_order`: `pick([ROMANTIC, CHILL])` with no ROMANTIC songs picks CHILL with no fallback flag, because CHILL is in the intent list.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Update existing tests that referenced removed functions: delete `classify` and `lift` tests (they move to Tasks 3 and 6) and adapt the selector tests to the new `pick` signature.
- [ ] **Step 4:** Run the full suite. Expected: PASS. Fix the engine call sites minimally, e.g. `selector.pick([target], mood)`, so the app keeps working until Task 9.
- [ ] **Step 5:** Commit with message `feat: eight song groups, play history, fresh-aware selection`.

### Task 3: Face states and music intent

**Files:** Create `src/moodmusic/mood/states.py`, `src/moodmusic/mood/intent.py`, `tests/mood/test_states.py`, `tests/mood/test_intent.py`

**Interfaces:**
- **`FaceState(str, Enum)`:** values `focused, deep_thought, love, tired, sleepy, stressed, bored, happy, excited, sad`.
  - `.label` per Global Constraints.
  - `.emoji`: 🧠 🤔 🥰 🥱 😴 😣 😐 😊 🤩 😢
- **Constants:**
  - `FAST_STATES`, `SLOW_STATES`
  - `EVIDENCE_WINDOW_S = {TIRED:240, BORED:240, SLEEPY:90, STRESSED:90}`
- **`Mode(str, Enum)`:** `MATCH`, `LIFT`. This is the same values as before, now moved here.
- **`Intent`:** frozen dataclass with `groups: list[MoodGroup]`, `fresh: bool`, `lifting: bool`, `note: str` (e.g. "lifting you up", "winding down").
- **`intent_for(state: FaceState, mode: Mode, step: int, hour: int, rng: random.Random) -> Intent`:**
  - FOCUSED → [FOCUS]
  - DEEP_THOUGHT → [PROFOUND]
  - LOVE → [ROMANTIC]
  - HAPPY → [UPBEAT]
  - EXCITED → [PARTY, INTENSE]
  - TIRED (lifting) → steps [[ROMANTIC, CHILL], [CHILL, UPBEAT], [UPBEAT]], with step clamped to the last
  - STRESSED (lifting) → steps [[CHILL], [CHILL, UPBEAT], [UPBEAT]]
  - BORED → [UPBEAT, PARTY, INTENSE], fresh=True, lifting=True
  - SLEEPY with `is_night(hour)` → [CHILL, PROFOUND], note "winding down". Otherwise steps [[UPBEAT], [PARTY]], note "waking you up", lifting=True.
  - SAD: MATCH → [MELANCHOLY]; LIFT → steps [[CHILL], [CHILL, UPBEAT], [UPBEAT]], lifting=True.
- **`is_night(hour: int) -> bool`:** `hour >= 21 or hour < 6`.

- [ ] **Step 1: Write failing tests.**
  - `test_labels_and_emojis_complete`
  - `test_focus_deep_love_happy_map`
  - `test_tired_lifts_even_in_match_mode`: `intent_for(TIRED, MATCH, 0, 14, rng).lifting is True` and its groups are `[ROMANTIC, CHILL]`. At step 2 the groups are `[UPBEAT]`, and at step 9 they stay `[UPBEAT]`.
  - `test_stressed_steps`
  - `test_bored_is_fresh_energetic`
  - `test_sleepy_day_vs_night`: hour 14 → `[UPBEAT]` with note "waking you up". Hour 22 → `[CHILL, PROFOUND]` with note "winding down". Hours 5 and 6 sit on the boundary: 5 is night, 6 is day.
  - `test_sad_follows_toggle`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement both modules. Re-point `Mode` imports across `src/` and `tests/` to `moodmusic.mood.intent`, and remove the re-export from `groups.py`.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: face states and state-to-music intent`.

### Task 4: Rolling feature tracker

**Files:** Create `src/moodmusic/mood/features.py`, `tests/mood/test_features.py`

**Interfaces:**
- Consumes `FrameSignals` (Task 1).
- **`Features`:** frozen dataclass with these fields:
  - `t`
  - `face_ratio_10s`
  - `gaze_on_ratio_30s`
  - `gaze_away_hold_s`: continuous seconds with face present and gaze off-screen. It resets on gaze-on, and also resets when the face is lost.
  - `head_motion_30s`: mean |Δyaw| + |Δpitch| per second.
  - `stillness_s`: seconds with head motion below 3°/s and mouth_motion below 0.02.
  - `mouth_motion_10s`
  - `blink_rate_per_min_60s`
  - `mean_blink_ms_60s`
  - `perclos_60s`: fraction of frames with `eye_open < 0.3`.
  - `long_closures_90s`: count of eye closures over 1.0 s.
  - `yawns_240s`: count of `jaw_open > 0.6` held at least 1.5 s.
  - `head_droop_deg_240s`: mean pitch, negative meaning down.
  - `smile_10s`, `cheek_squint_10s`
  - `brow_down_30s`, `brow_inner_up_10s`, `mouth_press_30s`
  - `glance_away_count_30s`: gaze transitions from on to off and back within 3 s.
  - `valence_30s`, `arousal_30s`
  - `emotion_30s`: dict
  - `observed_s`: total seconds with face since start.
- **`FeatureTracker(clock_free: no clock; caller passes t)`** with:
  - `.add(sig: FrameSignals, t: float) -> None`
  - `.features(t: float) -> Features`
  - Use deques of (t, value) trimmed to each window. All arithmetic is O(1) amortized per frame.

- [ ] **Step 1: Write failing tests** with synthetic signal streams at 8 Hz:
  - `test_gaze_away_hold_grows_and_resets`
  - `test_face_lost_does_not_count_as_gaze_away` (Review Focus 2): 20 s of `face=False` gives `gaze_away_hold_s == 0` and `face_ratio_10s == 0`.
  - `test_blink_rate_and_duration`: 15 blinks of 200 ms in 60 s give a rate of about 15 and mean of about 200 ms.
  - `test_perclos_and_long_closures`
  - `test_yawn_counted_once_per_event`
  - `test_stillness_breaks_on_talking`: mouth_motion 0.1 for 2 s resets `stillness_s`.
  - `test_glance_away_count`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: rolling facial feature tracker`.

### Task 5: Personal baselines

**Files:** Create `src/moodmusic/mood/baselines.py`, `tests/mood/test_baselines.py`

**Interfaces:**
- **`PersonalBaselines`:** holds per-key medians for `blink_rate_per_min_60s`, `mean_blink_ms_60s`, `perclos_60s`, `head_motion_30s`, `brow_down_30s`, `mouth_press_30s`, `smile_10s`, `gaze_on_ratio_30s` and `head_droop_deg_240s`, plus `observed_s`.
  - `.update(f: Features, dt: float) -> None`: a slow rolling median. Use a P² estimator or reservoir sampling capped at 2000 samples per key, sampled once every 5 s, to avoid per-frame cost.
  - `.get(key: str, default: float) -> float`
  - `.calibrate_rest(f: Features) -> None`: sets the at-rest keys from the calibration window: brow_down, mouth_press, smile, gaze_on_ratio, head_droop.
  - `.warm: bool`: true once `observed_s >= 1800`.
  - `to_dict` / `from_dict`
  - `load_baselines(path=None) -> PersonalBaselines` and `save_baselines(b, path=None)` at `data_dir()/"signal_baselines.json"`. Writes are atomic (temp file plus `os.replace`). A missing or corrupt file returns an empty instance.
- **`DEFAULTS: dict[str, float]`:** population defaults, seeded from the Task 1 checkpoint means, otherwise blink 15/min, blink 200 ms, perclos 0.05, head motion 4°/s, brow_down 0.15, mouth_press 0.1, smile 0.05, gaze_on 0.85, droop −5°.

- [ ] **Step 1: Write failing tests.**
  - `test_get_falls_back_to_default_until_samples`
  - `test_rolling_median_tracks_shift`: after 30 min of blink rate 25 the median is about 25.
  - `test_warm_after_1800s`
  - `test_calibrate_rest_sets_at_rest_keys`
  - `test_persist_roundtrip_and_corrupt_file`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: personal signal baselines (calibration + passive)`.

### Task 6: State rules

**Files:** Create `src/moodmusic/mood/rules.py`, `tests/mood/test_rules.py`

**Interfaces:**
- Consumes `Features`, `PersonalBaselines` and `dict[FaceState, float]` (correction bias, Task 7).
- **`Score`:** frozen dataclass with `value: float` in 0..1 and `reasons: list[str]`.
- **`score_states(f: Features, b: PersonalBaselines, bias: dict[FaceState, float] | None = None) -> dict[FaceState, Score]`:**
  - Each state's value is the mean of its cue scores. Each cue is a 0..1 ramp of how far the feature sits beyond the user's baseline.
  - Then add the bias and clamp to 0..1.
  - Each cue that contributes ≥0.5 appends a short human reason.
  - Cues per spec table (thresholds are named constants at the top of the file, seeded from Task 1's checkpoint):
    - **FOCUSED:** gaze_on_ratio high; head_motion at or below baseline; brow_down ≥ baseline (a frown helps, never hurts); mouth_motion low; emotion anger+disgust < 0.4.
    - **DEEP_THOUGHT:** gaze_away_hold_s ≥ 8 (full at 30); stillness_s high; neutral-ish face (|valence| < 0.3); mouth_motion low; face_ratio_10s ≥ 0.9.
    - **LOVE:** smile in 0.15..0.6 (soft, not a grin); glance_away_count ≥ 1 or downward gaze; |head_roll| ≥ 5; valence > 0.
    - **HAPPY:** smile ≥ 0.4 and cheek_squint ≥ 0.25 (Duchenne); valence > 0.2.
    - **EXCITED:** smile ≥ 0.6 or brow_inner_up high; arousal > 0.3; head_motion above baseline.
    - **TIRED** (240 s window): mean_blink_ms > baseline × 1.3; perclos > baseline × 2; head_droop below baseline by 5°; arousal < 0.
    - **SLEEPY** (90 s): long_closures ≥ 2; yawns ≥ 1; perclos high.
    - **STRESSED** (90 s), needing at least 2 of 3 tension cues plus either restlessness or negative emotion: brow_down above baseline; mouth_press above baseline; head_motion above baseline × 1.5 or valence < −0.2.
    - **BORED** (240 s): gaze_on_ratio below baseline − 0.2; flat face (smile and brow near baseline); yawns ≥ 1 without the SLEEPY eye cues; head_droop below baseline.
    - **SAD:** valence < −0.3 and arousal < 0, not explained by TIRED or FOCUSED cues (subtract 0.3 if either of those scores ≥ 0.6).
  - Slow-state thresholds are multiplied by 1.5 while `not b.warm`.
- **`decide(scores: dict[FaceState, Score], current: FaceState | None) -> tuple[FaceState | None, str]`:**
  - Return the best state if its value ≥ 0.6 and it beats the runner-up by ≥ 0.1. Otherwise return `(None, "")`, meaning hold.
  - The reason joins the winning state's top 2 reasons with ", ".

- [ ] **Step 1: Write failing tests**, each building a `Features` with a helper and asserting `decide(score_states(...))[0]`:
  - `test_focused_frown_reads_focused_not_stressed`: gaze on 0.95, brow_down 0.5, still, mouth quiet, no anger → FOCUSED.
  - `test_looking_away_still_reads_deep_thought`: gaze_away_hold 35 s, stillness 30 s, neutral → DEEP_THOUGHT. The reason contains "looking away".
  - `test_soft_smile_glance_away_reads_love`
  - `test_duchenne_smile_reads_happy`, `test_big_smile_energy_reads_excited`
  - `test_slow_heavy_blinks_droop_reads_tired`, `test_yawns_and_closures_read_sleepy`
  - `test_tension_plus_restless_reads_stressed`; `test_frown_alone_is_not_stressed` (a single cue)
  - `test_wandering_gaze_flat_reads_bored`
  - `test_talking_on_call_is_not_excited_or_deep_thought` (Review Focus 1): gaze on 0.8, mouth_motion 0.08, occasional smile 0.3, head motion slightly up → the result is FOCUSED, HAPPY or None, never EXCITED or DEEP_THOUGHT.
  - `test_weak_single_cue_holds` (Review Focus 4): only gaze slightly away, everything else at baseline → `(None, "")`.
  - `test_warmup_makes_slow_states_harder`: the same tired features give TIRED when warm and None when not warm.
  - `test_bias_tips_close_call`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: explainable face-state rules`.

### Task 7: State tracker and per-state corrections

**Files:** Create `src/moodmusic/mood/tracker.py` and `src/moodmusic/mood/state_corrections.py`. Tests: `tests/mood/test_tracker.py` and `tests/mood/test_state_corrections.py`. This task is additive: the old `smoother.py` and `corrections.py` stay until Task 10 deletes them.

**Interfaces:**
- **`FaceMood`:** frozen, with `state: FaceState = FaceState.FOCUSED`, `since: float = 0.0`, `reason: str = ""`, `valence: float = 0.0`, `arousal: float = 0.0`, `probs: dict = {}`, `candidate: FaceState | None = None`.
- **`StateTracker(hold_seconds: float)`** with:
  - `.update(decision: tuple[FaceState | None, str], f: Features, t: float) -> FaceMood`. Candidate and hold logic match the old smoother. A `None` decision clears nothing and keeps the current state and candidate timer. Valence, arousal and probs come from `f`.
  - `.force(state: FaceState, t: float) -> FaceMood`: reason "you said so".
  - `.state` and `.set_hold(seconds)`.
- **`StateCorrections(path)`** with:
  - `.record(predicted: FaceState, actual: FaceState) -> None`
  - `.bias() -> dict[FaceState, float]`: for each record, +0.05 to `actual` and −0.05 to `predicted`, over the last 50 records, capped ±0.25 per state. Cached and recomputed on `record`. A corrupt file or decode error gives an empty bias.
  - The default path is `data_dir()/"state_corrections.jsonl"`.

- [ ] **Step 1: Write failing tests.**
  - `test_hold_time_required`
  - `test_none_decision_holds_state` (Review Focus 4)
  - `test_force_immediate_with_reason`
  - `test_bias_accumulates_and_caps`
  - `test_old_corrections_file_ignored`: a `corrections.jsonl` in the same dir does not affect bias.
  - `test_corrupt_lines_skipped`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the new modules only. Leave the old pipeline untouched.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: state tracker with hold time and per-state corrections`.

### Task 8: Worker integration and calibration

**Files:** Modify `src/moodmusic/app/worker.py` and `tests/app/test_worker.py`

**Interfaces:**
- Pipeline per frame:
  1. `extract_signals(obs, raw_or_None, prev)`
  2. `features.add(sig, t)`
  3. Every 0.5 s: `f = features.features(t)`, then `baselines.update(f, dt)`, then `decision = decide(score_states(f, baselines, corrections.bias()), tracker.state.state)`, then `mood.emit(tracker.update(decision, f, t))`, then `features_ready.emit(f)`.
- When quality is not ok or there is no face, still feed signals with `face=False` so absence is tracked, but skip the model call. The emotion baseline (`apply_baseline`) still applies to `raw` before extraction.
- Calibration (20 s) also calls `baselines.calibrate_rest(features.features(t))` at the end and saves baselines.
- Baselines are saved every 5 minutes and on stop.
- New signal: `features_ready = Signal(object)`.
- `force_mood(state: FaceState)` records `corrections.record(predicted=tracker.state.state, actual=state)` and then `tracker.force`.
- `mood` now emits `FaceMood`. `corrections` becomes a `StateCorrections`.
- Constructor: replace `smoother` with `tracker: StateTracker`, and add `baselines: PersonalBaselines`, with `baselines_path: Path | None = None`. `set_hold_seconds` forwards to `tracker.set_hold`.

- [ ] **Step 1: Update and write failing tests** with fakes:
  - `test_emits_state_every_half_second_not_every_frame`: at 8 fps over 2 s, about 4 `mood` emits.
  - `test_no_face_frames_feed_absence`: the tracker sees `face=False` and the model is not called.
  - `test_calibration_sets_rest_baselines_and_saves`
  - `test_force_mood_records_state_correction`
  - `test_baselines_saved_on_stop`
  - Keep the existing error, backoff and stop tests, adapted.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests/app/test_worker.py` and then the full suite. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: worker infers face states from signals over time`.

### Task 9: Engine uses states and intents

**Files:** Modify `src/moodmusic/app/engine.py` and `tests/app/test_engine.py`

**Interfaces:**
- **`on_mood(state: FaceMood)`:** unchanged contract (records only). Every use of `MoodState` / `.group` becomes `FaceMood` / `.state`.
- **Choosing a song** (`_choose()`):
  1. `intent = intent_for(mood.state, self._mode, self._lift_step, hour, rng)`, where `hour = self._hour()` (an injectable `hour_fn: Callable[[], int] = lambda: datetime.now().hour`).
  2. `selector.pick(intent.groups, mood, fresh=intent.fresh, now=clock())`.
  3. The reason gets `" — " + intent.note` appended when `intent.note` is set.
- **Lift steps:** `_lift_step` resets to 0 when `mood.state` differs from the state of the last pick. It increments after each song chosen while `intent.lifting`.
- **Handled state:** `_handled_group` becomes `_handled_state: FaceState | None`. A state change is "new" when it differs from the handled state, and target equality is judged on `intent.groups[0]` versus the current pick's group.
- **`wrong_vibe(new_group: MoodGroup)`:** unchanged semantics.
- **`not_how_i_feel(state: FaceState)`:** forwards to `force_mood`.
- **Constructor:** add `hour_fn=None`.

- [ ] **Step 1: Update and write failing tests.**
  - `test_focused_state_plays_focus_group`
  - `test_tired_lift_advances_one_step_per_song_and_resets_on_state_change`
  - `test_bored_requests_fresh`
  - `test_sleepy_night_decided_at_selection_not_midsong` (Review Focus 5): `hour_fn` returns 20 while a song is playing, then 21 mid-song. There is no `play` or `queue` until the song boundary, and the next pick uses the night groups.
  - `test_reason_includes_intent_note`
  - Keep all existing behaviour tests (pause, device, manual back-off, rate limit), adapted to states.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: engine plays music for face-state intents`.

### Task 10: UI — states, reasons, signals panel, eight groups

**Files:** Modify `src/moodmusic/ui/mood_picker.py`, `widget.py`, `dashboard.py` and `review_dialog.py`, plus `src/moodmusic/ui/main.py` (wiring). Tests: `tests/ui/test_widget.py`, `test_dashboard.py` and `test_review.py`, plus a new `tests/ui/test_mood_picker.py`.

**Interfaces:**
- **`MoodPicker`:**
  - `.ask_state(parent, title) -> FaceState | None` shows 10 buttons with emoji and label.
  - `.ask_group(parent, title) -> MoodGroup | None` shows 8 buttons.
  - "Not how I feel" uses `ask_state` and "Wrong vibe" uses `ask_group`.
- **Widget:**
  - The mood line shows `f"{state.emoji} {state.label}"`, plus "steady for N min".
  - Its tooltip is `FaceMood.reason`, e.g. "Deep in thought: looking away 40 s, very still".
  - The quality-issue override is unchanged.
- **Dashboard:**
  - **Signals panel:** replaces nothing; it sits below the emotion bars. Fed by `worker.features_ready`, it shows one bar per signal against the user's baseline marker: gaze on screen, blink rate, stillness, smile, tension (mean of brow_down and mouth_press) and eye openness (1 − perclos).
  - **State timeline:** a coloured strip for the session (last 60 min), one segment per state change. Keep the positive/energy chart underneath.
  - Now playing shows the pick reason, which includes the intent note.
- **Review dialog:** 8 group lists plus Unsorted, in the order Focus, Profound, Romantic, Chill, Upbeat, Party, Melancholy, Intense, Unsorted.
- **`main.py`:** constructs `StateTracker`, `PersonalBaselines` (via `load_baselines`) and `StateCorrections(data_dir()/"state_corrections.jsonl")`, and connects `features_ready` to the dashboard.
- **Remove the old pipeline:**
  - Delete `mood/smoother.py`, `mood/corrections.py` and their tests.
  - The `selector.py` reason uses `FaceMood.state.label` only; drop the Task 2 fallback.
  - Grep must find no remaining `MoodState`, `MoodSmoother` or `CorrectionStore` references.

- [ ] **Step 1: Write and update failing tests.**
  - `test_widget_shows_state_label_and_reason_tooltip`
  - `test_not_how_i_feel_offers_ten_states`
  - `test_wrong_vibe_offers_eight_groups`
  - `test_dashboard_signals_panel_updates_from_features`
  - `test_dashboard_timeline_segments_on_state_change`
  - `test_review_has_nine_lists_in_order`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: UI for face states, reasons, signals and eight groups`.

### Task 11: Sort tools

**Files:** Create `src/moodmusic/tools.py` and `tests/test_tools.py`

**Interfaces:**
- `python -m moodmusic.tools export-unsorted [--all] [--out FILE]` writes `uri<TAB>title<TAB>artist<TAB>group` for unsorted songs, or for all songs with `--all`. The default output is stdout.
- `python -m moodmusic.tools apply-sort FILE` reads `uri<TAB>group` lines, ignoring extra columns, blank lines and `#` comments.
  - Each line becomes `library.set_group(uri, group, by_user=True)`. `unsorted` clears the override (`set_group(uri, UNSORTED, by_user=False)`).
  - It prints `applied N, skipped M` and lists each unknown URI or bad group with its line number.
  - Exit code is 0 when there are no errors, 1 otherwise.
- Functions `export_rows(library, all_songs: bool) -> list[str]` and `apply_lines(library, lines: list[str]) -> tuple[int, list[str]]`, so they are testable without the CLI.

- [ ] **Step 1: Write failing tests.**
  - `test_export_unsorted_only`
  - `test_export_all`
  - `test_apply_sets_override`
  - `test_apply_unsorted_clears_override`
  - `test_apply_reports_bad_lines_with_numbers`
  - `test_apply_accepts_export_format_roundtrip`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit with message `feat: export-unsorted / apply-sort tools`.

> **After Task 11 (controller, with the user):**
> 1. Run `export-unsorted --all`.
> 2. Claude re-sorts all 47 songs into the 8 groups.
> 3. Run `apply-sort`.
> 4. The user reviews the result on the review screen.

---

## Spec coverage check

| Spec item | Task |
|---|---|
| Nine states + Sad, labels | 3 |
| Multiple signals (blendshapes, gaze, head pose, blinks, yawns, stillness) over time | 1, 4 |
| Relative to the user (calibration + passive baselines, warm-up) | 5, 8 |
| Explainable rules, reasons on screen | 6, 10 |
| Single-cue overreaction / jitter guards | 6, 7 |
| State → music intent, lift rules, Fresh, Sleepy day/night | 3, 9 |
| Eight song groups, fallbacks, tags | 2 |
| Play history for Fresh | 2 |
| Corrections per state, persistent, old file ignored | 7, 8 |
| Widget, picker, dashboard signals + timeline, review | 10 |
| Export/apply sort tooling; Claude re-sort | 11 + post-step |
| Gaze reliability spike with fallback | 1 + checkpoint |
| Privacy (numbers only) | 1, 5, 7, 8 |
