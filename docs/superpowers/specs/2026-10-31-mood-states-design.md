# Mood Music: emotionally intelligent states

*Date: 2026-10-31. Status: draft for approval. Builds on `2026-10-31-mood-music-design.md` (the "base spec"); everything there still holds unless changed here.*

## Why

The first version maps your face to one emotion and then to one of five song groups. That is too blunt for how people actually look at a desk. The user's examples:

- **Frowning while focused.** A frown at the screen while concentrating is not anger. Focus music should play.
- **Deep thought.** A neutral face, looking off to the side, quiet and still, means thinking deeply. A profound, reflective song should play.
- **Love or shyness.** A soft smile and a shy glance away call for a love song.

The goal is for the app to read several signals together over time, infer what the person is *doing or feeling*, and choose music for that. In short, it should be emotionally intelligent rather than reacting to one expression.

## Goals

- Recognise **nine states** from the face: Focused, Deep in thought, Love/shy, Tired, Sleepy, Stressed, Bored, Happy, Excited. Sad is also recognised when it clearly shows.
- Combine multiple signals over a time window:
  - emotion scores
  - the 52 facial-movement scores MediaPipe already computes, which are currently unused
  - gaze direction
  - head pose and movement
  - blink rate and eye openness
  - yawns
  - stillness
- Interpret signals **relative to this person**, extending the existing calibration and "Not how I feel" corrections.
- Map each state to a **music intention** and a song group, including lift behaviour where the user asked for it.
- Re-sort the user's library into the new song groups (done by Claude in-session; see Song sorting).
- Show the inferred state and a plain reason on screen, e.g. "Deep in thought: looking away, still for 40 s".

## Non-goals

- True micro-expressions or blush detection. The base spec's honesty note still applies, and shyness is read from smile, gaze and head cues, not skin colour.
- Training a new ML model or collecting a dataset. States are inferred by explainable rules over existing model outputs, tuned per user.
- Voice or microphone input. "Not speaking" is inferred from a still mouth (jaw and lip movement), not from audio.
- Automatic song sorting for future additions. The user chose to ask Claude again when they add songs.

## Anti-goals

- **Single-cue overreaction.** A frown must not flip the state to Stressed by itself, and a glance away must not trigger Deep thought by itself. States need several agreeing signals held over time.
- **Jittery state changes.** The base spec's hold-time behaviour must still apply.
- **Opaque guesses.** If the user can't tell why the app thinks they're "bored", they can't correct it. Every state shows its reason.
- **Losing what works.** Calibration, corrections, Match/Lift and all the reliability behaviour stay.

## The states

| State | Signals that must agree (relative to the user's calibrated baseline) | Music intention | Song group |
|---|---|---|---|
| Focused | Gaze on screen; few head movements; brows lowered or neutral; mouth still; no strong anger or disgust in the emotion scores | Match | **Focus** |
| Deep in thought | Neutral or soft face; gaze away from screen (side or up) held for a while, or eyes unfocused; very still; mouth still | Match | **Profound** |
| Love / shy | Soft or small smile; glances down or away and back; slight head tilt; positive emotion | Match | **Romantic** |
| Happy | Real smile (mouth corners up *and* eyes crinkling); positive emotion | Match | **Upbeat** |
| Excited | Big smile and/or raised brows; high energy; more head movement | Match | **Party** |
| Tired | Blinks slower and longer than baseline; eyelids lower than baseline; head drooping, sustained over minutes | **Lift** | Romantic/Chill (warm) → Upbeat, stepwise |
| Sleepy | Eyes closing for long periods; yawns; head nodding | Time of day: **wake-up** (Upbeat → Party) during the day, **wind-down** (Chill/Profound) at night | depends |
| Stressed | Brow tension *plus* lip pressing or jaw clench *plus* restless movement or negative emotion | **Lift** | Chill → Upbeat, stepwise |
| Bored | Gaze wandering; head resting or slumped; flat expression; yawns without the sleepy eye signs | **Lift** | **Fresh**: energetic songs least recently played |
| Sad (when it shows) | Negative emotion with low energy, not explained by focus or tiredness | Match/Lift toggle (as today) | Melancholy, or a lift toward Chill/Upbeat |

When nothing is clear, the app keeps the current state (it holds rather than guesses). Day versus night for Sleepy uses local time (night = 21:00–06:00; *builder may make this a setting*).

The global **Match/Lift toggle** still exists. The table's "Lift" rows are the user's standing choice for those states, so they lift even in Match mode. The toggle governs the "Match" rows that have a natural opposite (Sad) and can be revisited later.

## Song groups

The groups change from five to eight:

**Focus, Profound, Romantic, Chill, Upbeat, Party, Melancholy, Intense**, plus Unsorted.

- **Fresh** is not a group. It means "energetic groups (Upbeat, Party, Intense), preferring songs least recently played".
- **Intense** stays for aggressive or high-energy songs (e.g. Shoorveer, Worldwide Choppers). It is used for Excited (mixed with Party) and in the Bored lift.
- Fallback when a group is empty: the nearest group by intention, e.g. Focus → Chill → Profound. The builder defines the full table.

## Song sorting

- Existing library: Claude re-sorts all songs into the eight groups in-session, with user-filed overrides as today, and the user reviews them.
- Future songs: the user asks Claude again. To make that quick, add a small command:
  - `python -m moodmusic.tools export-unsorted` writes a simple file (title, artist, uri).
  - `python -m moodmusic.tools apply-sort <file>` applies groups as user overrides.
  - Last.fm tagging stays as a first pass for songs it can classify.

## How it reads the face (constraints, not a full design)

- **Inputs per frame:** the emotion reading (as today); MediaPipe blendshapes (e.g. `browDownLeft/Right`, `browInnerUp`, `eyeBlinkLeft/Right`, `eyeSquint*`, `eyeLookOut*/In*/Up*/Down*`, `mouthSmile*`, `mouthPress*`, `jawOpen`, `mouthClose`); and head pose and gaze from landmarks.
- **Features over time:** per-signal rolling statistics over roughly 5–60 s windows, e.g.:
  - blink rate and mean blink duration;
  - percentage of time eyes are mostly closed;
  - gaze-on-screen ratio and how long gaze is held away;
  - head-movement energy;
  - yawn count;
  - smile duration;
  - brow and lip tension.
- **Personal baselines:** calibration (the existing 20 s neutral look) also records each signal's baseline. Rules compare against the user's own baseline, not absolute numbers. Corrections ("Not how I feel" → pick a state) nudge that user's thresholds.
- **Decision:** explainable, rule-based scoring per state from the features, with the strongest sufficiently-confident state winning, then the existing hold-time smoothing. The reason string comes from the features that drove the decision.
- **Stays local and in memory:** all inputs and features stay on the user's machine. Only numbers (baselines, thresholds, corrections) persist, as in the base spec.
- **Runtime budget:** performance stays within the base spec's all-day budget (8 fps analysis; features are cheap arithmetic).

## Screens

- **Widget:** shows the state with an emoji and label (e.g. "🤔 Deep in thought"), how long it has held, and the reason on hover.
- **"Not how I feel":** offers the nine states plus Sad.
- **Dashboard:**
  - The emotion bars are joined by a small "signals" panel showing gaze on screen, blink rate, stillness, smile and tension against the user's baseline, so the user can see why a state was chosen.
  - The mood graph shows a state timeline instead of only positive/energy lines (*builder may keep both*).
- **Review screen:** shows the eight groups.

## Decided by the user

- The nine states above, plus Sad when it shows.
- Tired and Stressed lift the user up. Bored lifts with fresh, energetic songs. Sleepy wakes the user by day and winds them down at night.
- The music intention for each state as in the table, including Focus for a focused frown, Profound for deep thought, and Romantic for love/shyness.
- Song sorting for future additions: ask Claude again (no API key, no manual-only flow).

## Claude's calls

- Rule-based, explainable state inference over existing model outputs, rather than a new ML model.
- Night is 21:00–06:00 for Sleepy (may become a setting).
- Eight song groups: "Fresh" is a selection rule, not a group.
- An export/apply-sort command to make Claude re-sorting quick.
- The two open bugs from the first run (the Qt crash and the phone-playback transfer, plus the widget not showing music the user started themselves) are fixed **before** this work starts.

## Answers to builder questions (Claude's calls unless marked)

1. **Head pose and gaze.**
   - `FaceObservation` already carries the 478 landmarks (`vision/types.py`).
   - Head pose comes from the landmarks, or from MediaPipe's facial transformation matrix. Enable `output_facial_transformation_matrixes` if helpful.
   - Gaze comes from the iris landmarks plus the `eyeLook*` blendshapes.
   - **The first plan task is a spike.** Using recorded numbers from the user's own webcam (no frames saved), prove that "looking at the screen" versus "looking away", blinks and yawns can be told apart. If gaze proves unreliable, Deep in thought and Love/shy fall back to head pose plus stillness, and the reason text says so.
2. **Baselines beyond calibration.**
   - Calibration stays short (20 s neutral) and records the at-rest baselines it can see.
   - Every other baseline (blink rate and duration, head movement while working, gaze-away frequency, yawns) is **learned passively** as a slowly-updating rolling median over the first sessions and kept updating.
   - Until about 30 minutes of data exist, the slow states (Tired, Bored, Stressed) use conservative defaults and need stronger evidence.
   - Baselines persist as numbers only.
3. **Corrections.**
   - A correction forces the chosen state immediately, as today.
   - It also records a per-state bias: it raises the picked state's score slightly and lowers the rejected state's, given similar features. This is capped so a few corrections can't break detection.
   - Learning is persistent.
4. **Old labels.** The nine states plus Sad **replace** the old five-label mood scheme everywhere: smoother keying, the widget, the picker, corrections and the dashboard. Emotion scores become one input among several. Old corrections are discarded on migration (they are keyed on the old labels).
5. **Lift rows.**
   - *User decision:* Tired and Stressed always lift, even when the toggle is on Match. Bored lifts with Fresh.
   - Lifting advances **one step per song**.
   - Lifting stops when the state ends: the next song follows the new state.
   - Sleepy by day steps Upbeat → Party once per song.
6. **Hold times.**
   - Fast states (Focused, Deep in thought, Love/shy, Happy, Excited, Sad) use the existing hold presets (default 45 s, Responsive 20 s).
   - Slow states (Tired, Sleepy, Stressed, Bored) need sustained evidence over a longer window (about 3–5 min for Tired and Bored, about 1–2 min for Sleepy and Stressed). That evidence then passes through the same hold.
7. **Fresh.**
   - Store the app's own play history locally (song uri plus last-played time; numbers only).
   - Fresh prefers songs never played or least recently played by the app.
   - Spotify's recently-played history is not used, because it needs an extra permission the app doesn't request.
8. **Re-sort.**
   - The plan includes the export and apply-sort tooling and the five-to-eight group migration.
   - Claude's in-session re-sort of the user's library is a step after the tooling task, done by the controller with the user reviewing.
   - The `apply-sort` format is one line per song: `uri<TAB>group`, using group names only. `unsorted` is allowed and clears an override.
9. **Sleepy at 21:00.** Day or night is decided when the next song is chosen. It never switches mid-song.

## Left to the builder

- Exact feature definitions, window lengths, thresholds and scoring weights, tuned against the user's real sessions.
- How corrections update per-state thresholds.
- Exact fallback tables between the eight groups and lift step sequences.
- Visual details of the signals panel and state timeline.
- Migrating the existing library (five groups → eight) and settings. The Claude re-sort replaces the old groups for this user; any other user's old groups map Chill→Chill, Upbeat→Upbeat, Melancholy→Melancholy, Intense→Intense, Focus→Focus.

## Success looks like

Over a week at the desk:
- a frown while working plays Focus songs, not Intense or sad ones;
- staring off thinking brings a Profound song within a minute or so;
- a shy smile brings a love song;
- tiredness and stress are met with music that gradually lifts;
- when the state is wrong, the reason makes clear why, and one correction fixes it.
