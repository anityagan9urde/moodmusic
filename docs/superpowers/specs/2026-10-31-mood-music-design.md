# Mood Music: design

*Date: 2026-10-31. Status: draft for approval.*

## What this is and why

A free desktop app for people working at a desk. It watches the user's face through their webcam, works out their mood, and plays songs from their **own Spotify library** that fit that mood. The app either **matches** the mood or **lifts** it toward a better one, and the user chooses which.

It starts as a free tool that anyone with Spotify Premium can download and use. All face analysis happens on the user's own computer.

## Goals

- Read the user's emotional state from a normal webcam, live, accurately enough that it feels right to them.
- Pick and play fitting songs from a playlist (or Liked Songs) the user chooses, on their Spotify account.
- Two modes: **Match my mood** and **Lift my mood**.
- Two views: a **simple floating widget** and an **advanced dashboard**.
- Run on **Windows and macOS** as a normal double-click install. Users never install Python.
- Be **stable enough to leave running all day**.

## Non-goals (for now)

- Detecting true micro-expressions (involuntary flickers of 1/25 to 1/5 of a second). Webcams can't do this reliably. The app reads subtle expressions and sustained mood, and says so honestly.
- Discovering new music outside the user's chosen playlist.
- Music services other than Spotify.
- Accounts, servers, a website, or any cloud backend.
- Charging money, or getting Spotify's public-app approval.
- Mobile.

## Anti-goals (would count as failure even if it technically works)

These come from the user describing a bad week with the app:

1. **"My expressions weren't captured properly."** For example, a resting face read as sad or angry, or bad lighting causing random moods.
2. **"The song pairing didn't work."** The songs don't feel like the mood, and the user can't see why or fix it.
3. **"Too buggy because it runs locally."** Crashes, silent failures, the camera or Spotify dropping without explanation, or high CPU use.

Also:

4. Face video or images leaving the machine, or being saved to disk.
5. Music jumping around because of a sneeze, a glance away, or a two-second frown.

## Constraints

- **Spotify Premium is required.** Spotify's API only allows playback control for Premium accounts. Spotify must be open on some device (desktop app, phone, web player).
- **Spotify app limits.** Spotify won't let a new, unapproved app serve the general public. **Decision: each user brings their own Spotify developer key.** On first launch, a guided setup walks the user through creating a free Spotify developer app (about 5 minutes) and pasting its Client ID. With this setup there's no shared key, no user cap, and no Spotify approval needed.
- **Spotify no longer gives new apps song-mood data** (audio features and recommendations were closed in late 2024). Song moods therefore come from **Last.fm tags** (see Music below).
- **Everything runs locally**, with no backend of ours. The only network calls go to Spotify and Last.fm.
- **Platforms:** Windows 10/11 and macOS on Apple Silicon. *(Claude's call: Intel Macs are best-effort, not a requirement, because support for the face libraries there is shrinking.)* Must handle each OS's camera permission prompts.
- Typical library is about 300 songs, but it must cope with **several thousand**.

## Decisions made with the user

| Topic | Decision |
|---|---|
| Purpose | Mood-driven Spotify playback while at a desk |
| Modes | Both "Match my mood" and "Lift my mood", switchable any time |
| Song source | A user-chosen playlist or Liked Songs, auto-sorted by vibe/tags/artist |
| Audience | Free tool, each user uses their own Premium account and own Spotify key |
| Face analysis | Best-available local analysis; no cloud |
| Platforms | Windows and macOS |
| Views | Simple = floating widget (mockup A); Advanced = full dashboard (mockup B) |
| Mood change mid-song | **User setting**: switch immediately, or wait for the song to end |

## How it works

### 1. Face and mood reading

- **Camera:** the default webcam, with a picker if there are several. Frames are processed in memory and never stored or sent anywhere.
- **Face tracking:** Google **MediaPipe Face Landmarker** gives the face mesh plus 52 "blendshape" scores for small facial movements (brow raise, lip-corner pull, eye squint and so on). It runs in real time on a CPU.
- **Emotion model:** **HSEmotion** (the EmotiEffLib model trained on AffectNet) is run on the cropped face. It gives probabilities for 8 emotions (neutral, happy, sad, surprise, fear, disgust, anger, contempt) plus **valence** (how positive) and **arousal** (how energized).
- **Personal calibration (addresses anti-goal 1):** on first run, the user relaxes for about 20 seconds while the app records their neutral baseline. The baseline is stored as numbers only, never images. Later readings are measured *relative to this baseline*, so a naturally downturned resting face doesn't read as sad. Users can recalibrate at any time.
- **Quality check (anti-goal 1):** the app detects and tells the user about: no face, multiple faces, face too far or off-angle, too dark or backlit, camera blocked. While quality is poor it **does not change the music**, and it shows why.
- **"That's not how I feel" correction (anti-goal 1):** one click and a pick of the right mood. This corrects the current state immediately and is logged locally to gently adjust that user's baseline and thresholds over time.
- **Smoothing (anti-goal 5):** frame readings are averaged over a rolling window. A new mood must **hold for a set time** (default about 45 seconds; sensitivity is user-adjustable: Relaxed / Normal / Responsive) before it counts as a mood change.
- **Away from desk:** if no face is seen, the current music keeps playing. After a configurable time away (default 10 min), playback pauses, and it resumes when the user returns. This can be turned off.

### 2. Mood model

The app reduces everything to a point on two axes, **positive ↔ negative** (valence) and **calm ↔ energized** (arousal). It then maps that point to one of five **mood groups**, which songs are also sorted into:

| Mood group | Face state | Example song tags |
|---|---|---|
| **Upbeat** | positive + energized | happy, feel good, upbeat, party, dance |
| **Chill** | positive + calm | chill, relaxing, mellow, peaceful, acoustic |
| **Melancholy** | negative + calm | sad, melancholy, heartbreak, rainy day |
| **Intense** | negative + energized | aggressive, angry, heavy, energetic, rock-out |
| **Focus** | neutral (most desk time) | instrumental, ambient, lo-fi, study, focus |

**Match mode** plays from the group matching the current mood.
**Lift mode** steers toward a better state step by step rather than jumping:
- Melancholy → Chill → Upbeat
- Intense → Chill
- Chill → Chill (with occasional Upbeat)
- Upbeat → Upbeat
- Focus → Focus

*(The exact tag lists, thresholds, and lift steps are the builder's to tune. The five groups and two modes are fixed.)*

### 3. Music: sorting the library

- **Source:** the user picks one playlist, or Liked Songs, in the setup (and can change it later).
- **First scan (anti-goal 2):** for each song, fetch its Last.fm tags (`track.getTopTags`) and score them against each mood group's tag list.
  - If the song has too few useful tags, fall back to the **artist's** top tags.
  - If that's still unclear, the song goes in **Unsorted**. Unsorted songs aren't played automatically until the user files them, and the app suggests a group for each.
- The scan runs **in the background**. Playback can start as soon as each group has a handful of songs. Progress is shown. It respects Last.fm rate limits. About 300 songs should take a couple of minutes; thousands may take longer.
- **Results are cached locally.** Later launches only scan songs that are new to the playlist and drop removed ones.
- **Review screen:** the user can see each group's songs and drag songs between groups.
- **"Wrong vibe" button (anti-goal 2):** while a song is playing, one click lets the user move it to the right group. It's saved permanently and overrides the tags.
- **Explanations (anti-goal 2):** every pick carries a short reason, e.g. "Chill: you look calm and positive; tagged *mellow, acoustic*."
- Last.fm API key: **builder's call** (see "Left to the builder").

### 4. Playback

- Uses the Spotify Web API on whatever device is active. If no device is active, the app lists the user's available devices and asks which to use. If none are available, it says "Open Spotify on any device" instead of failing silently.
- Avoids repeating songs: the recently played songs in a group aren't replayed until most of the group has played.
- **Mood change mid-song:** a user setting, either "Wait for the song to end" (**default**) or "Switch right away".
- Manual play/pause/skip from the widget always works. If the user manually picks something in Spotify itself, the app backs off (*builder's call on exact rule; e.g. pause auto-picking for that song*).
- An **on/off switch** pauses all auto-picking without closing the app.

### 5. Screens

**First-run setup (guided, step by step):**
1. Welcome and privacy promise (video never leaves your computer, nothing recorded).
2. Spotify key: illustrated walkthrough to create a free Spotify developer app, set the redirect address the app shows, paste the Client ID. Then log in to Spotify (browser opens, user approves). Must check for Premium and say so clearly if missing.
3. Camera: permission prompt and live preview to confirm framing and lighting.
4. Calibration: about 20 seconds of relaxed neutral face.
5. Pick playlist or Liked Songs → scan starts → go to the widget.

**Simple view (widget, approved mockup A):** small, always-on-top, draggable, stays in a corner. Shows the current mood (emoji + label), how long it's held, the current song with art, ⏮ ⏸ ⏭, a Match/Lift toggle, and "not how I feel" and "wrong vibe" buttons. Camera preview hidden. A status dot shows camera, Spotify and quality problems.

**Advanced view (dashboard, approved mockup B):** live camera with face mesh overlay, emotion breakdown bars, a positive and energy graph for the current session (last hour), now playing with "picked because…", mode toggle, and access to settings and the song-group review screen. One click switches between widget and dashboard.

**Settings:** camera choice, sensitivity, switch-immediately vs wait-for-song, away-pause timer, recalibrate, change playlist, rescan, re-enter Spotify key or log out, start at login (on/off).

The app also sits in the system tray (Windows) or menu bar (Mac) so closing the window doesn't quit it.

## Reliability requirements (anti-goal 3)

This is a core requirement, not polish:

- **Camera:** survives unplug or replug, sleep/wake, and another app grabbing the camera. Shows the issue and retries automatically.
- **Spotify:** refreshes the login token automatically. Handles no active device, Premium lapse, rate limiting and network drops with clear messages and retries, never a crash or silent stop.
- **Last.fm:** scan failures are retried later. A failed scan never blocks playback of already-sorted songs.
- **Performance:** runs all day. Target modest CPU use on a typical laptop (e.g. analyze about 5 to 10 frames per second, which is plenty for mood) and no memory growth over hours.
- **Crash safety:** an unexpected error in one part (camera, music, UI) shouldn't take the app down. Errors go to a local log file the user can open from settings.
- **Tested as packaged:** the installed Windows and macOS builds are tested, not just the dev setup, including the macOS camera permission. Signing is out of scope for now (see Rollout).

## Privacy

- No video, images or face data leave the machine. No frames are written to disk.
- Stored locally only: settings, Spotify login tokens (in the OS secure store where available), the calibration baseline (numbers), mood corrections, and the song-mood cache.
- Mood history for the dashboard graph is kept **for the current session only** (not saved). *My call; easy to change later.*
- No analytics or telemetry.

## How it gets built (Claude's calls, user didn't object)

- **Language:** Python, because MediaPipe and HSEmotion are best supported there.
- **Emotion model runtime:** ONNX Runtime rather than full PyTorch, to keep the download small and fast on CPU. *(builder may swap if accuracy demands it)*
- **UI:** PySide6 (Qt). One cross-platform toolkit handles the always-on-top widget, dashboard, tray icon and camera preview.
- **Spotify:** Spotify Web API with the PKCE login flow (only a Client ID is needed, no secret), using a local loopback redirect (`http://127.0.0.1:<port>/callback`).
- **Packaging:** a standalone app per OS (e.g. PyInstaller or Briefcase): an `.exe` installer for Windows and a `.dmg` for macOS.

## Rollout, licensing and signing (user's answers)

- **Only the user will use it at first.** No beta stage or log-sharing for now. Accuracy is judged by the user's own week of use (see "Success looks like").
- **Non-commercial for now.** Commercial plans are deferred. The non-commercial-licensed HSEmotion model and a bundled Last.fm key are fine. *Known risk:* a future paid version would need a commercially licensed emotion model and its own accuracy re-tuning. The builder should keep the emotion model behind a clean interface so it can be swapped.
- **No paid code signing for now.** Builds are unsigned. The app and README include short first-run instructions for getting past the Windows SmartScreen warning and the macOS "unverified developer" warning (right-click → Open). *Claude's call:* the user's machine is Windows, so the Windows build is built and tested first. The code stays cross-platform from day one, and the macOS build is produced and smoke-tested on a cloud macOS runner (e.g. GitHub Actions), including the camera-permission prompt.

## Distribution and updates (Claude's call)

- Downloads come from **GitHub Releases**: a Windows installer and a macOS `.dmg`.
- **No auto-installing updater** in the first version. On launch, the app checks GitHub for a newer release and shows an "Update available" link. This keeps packaging simple while making sure users on old versions find out when a Spotify or Last.fm change needs a fix.

## Mockups

The approved layout choices (A = widget, B = dashboard) are saved at `docs/superpowers/specs/assets/2026-10-31-layout-mockups.html`. They are **layout direction, not final visual designs**. Option C in that file was not chosen, apart from the tray/menu-bar icon described above.

## Left to the builder

- Exact tag-to-group keyword lists and scoring.
- Exact smoothing window, hold time and sensitivity presets (within the behavior above).
- Exact lift-mode steps and pacing.
- How the "not how I feel" corrections adjust thresholds.
- Visual styling of the widget and dashboard (within the approved layouts).
- Local storage format and locations.
- Last.fm API key approach: bundle the app's own key (Last.fm allows this for non-commercial use) vs. user-supplied. Bundling is preferred so setup stays short.
- Rule for backing off when the user manually controls Spotify.
- Test strategy, with the reliability requirements above as the bar.

## Success looks like

The user runs it for a week at their desk and:
- the mood it shows usually matches how they feel, and corrections are rare and quick;
- the songs feel right for the mode they chose, and when one doesn't, they can see why and fix it in one click;
- it never crashes or goes quietly silent, and anything wrong is explained on screen.
