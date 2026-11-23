"""Rolling-window facial features computed from per-frame signals (numbers only)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from moodmusic.vision.signals import FrameSignals

MAX_WINDOW_S = 240.0
DEFAULT_DT = 1 / 8
BLINK_CLOSED = 0.5  # eye_open below this = eye closed (blink detection)
PERCLOS_CLOSED = 0.3  # eye_open below this counts toward PERCLOS
LONG_CLOSURE_S = 1.0
YAWN_JAW = 0.6
YAWN_MIN_S = 1.5
STILL_HEAD_DEG_S = 3.0  # on smoothed head angles, so landmark jitter doesn't count
STILL_MOUTH = 0.02  # on smoothed mouth motion
HEAD_SMOOTH_S = 0.5
MOUTH_SMOOTH_S = 1.0
GLANCE_MIN_S = 0.4  # shorter excursions are noise, not glances
GLANCE_MAX_S = 3.0
GAZE_OFF, GAZE_ON = 0.40, 0.30  # hysteresis around the calibrated screen centre
YAW_OFF, YAW_ON = 25.0, 20.0
BLIP_S = 0.5  # on-screen blips or face dropouts shorter than this don't end a look away
LOOK_DOWN = 0.30  # gaze this far below the screen = reading the desk/phone


@dataclass(frozen=True)
class Features:
    t: float = 0.0
    face_ratio_10s: float = 0.0
    gaze_on_ratio_30s: float = 0.0
    gaze_away_hold_s: float = 0.0
    head_motion_30s: float = 0.0  # deg/s
    stillness_s: float = 0.0
    mouth_motion_10s: float = 0.0
    blink_rate_per_min_60s: float = 0.0
    mean_blink_ms_60s: float = 0.0
    perclos_60s: float = 0.0
    long_closures_90s: int = 0
    yawns_240s: int = 0
    head_droop_deg_240s: float = 0.0  # mean pitch; negative = head down
    head_tilt_10s: float = 0.0  # mean |roll|, degrees
    smile_10s: float = 0.0
    cheek_squint_10s: float = 0.0
    brow_down_30s: float = 0.0
    brow_inner_up_10s: float = 0.0
    mouth_press_30s: float = 0.0
    glance_away_count_30s: int = 0
    valence_30s: float = 0.0
    arousal_30s: float = 0.0
    emotion_30s: dict[str, float] = field(default_factory=dict)
    observed_s: float = 0.0


@dataclass(frozen=True)
class _Frame:
    t: float
    face: bool
    s: FrameSignals
    head_speed: float
    on: bool  # gaze on the (calibrated) screen
    down: bool  # looking down at the desk: eyelids look closed, so skip eye-closure cues


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class FeatureTracker:
    """Feed every frame with add(); read rolling features with features(t)."""

    def __init__(self) -> None:
        self._frames: deque[_Frame] = deque()
        self._blinks: deque[tuple[float, float]] = deque()  # (end time, duration)
        self._long_closures: deque[float] = deque()
        self._yawns: deque[float] = deque()
        self._glances: deque[float] = deque()
        self._last_t: float | None = None
        self._smooth_pose: tuple[float, float] | None = None
        self._mouth_ema = 0.0
        self._closed_since: float | None = None
        self._yawn_since: float | None = None
        self._center = (0.0, 0.0, 0.0)  # gaze_x, gaze_y, yaw when looking at the screen
        self._on = True
        self._away_since: float | None = None  # start of the current look-away episode
        self._back_since: float | None = None  # on-screen (or face gone) since, mid-episode
        self._back_on: bool = True  # was the interruption "back on screen" (vs face gone)
        self._away_hold = 0.0
        self._still = 0.0
        self._observed = 0.0

    def set_screen_center(self, gaze_x: float, gaze_y: float, yaw: float) -> None:
        """Where the user's eyes and head point when looking at their screen (calibration)."""
        self._center = (gaze_x, gaze_y, yaw)

    def gaze_center(self, t: float, seconds: float) -> tuple[float, float, float]:
        frames = [f.s for f in self._frames if f.face and f.t > t - seconds]
        if not frames:
            return self._center
        n = len(frames)
        return (sum(s.gaze_x for s in frames) / n, sum(s.gaze_y for s in frames) / n,
                sum(s.head_yaw for s in frames) / n)

    def _on_screen(self, sig: FrameSignals) -> bool:
        cx, cy, cyaw = self._center
        dx, dy, dyaw = abs(sig.gaze_x - cx), abs(sig.gaze_y - cy), abs(sig.head_yaw - cyaw)
        if self._on:
            self._on = not (dx > GAZE_OFF or dy > GAZE_OFF or dyaw > YAW_OFF)
        else:
            self._on = dx < GAZE_ON and dy < GAZE_ON and dyaw < YAW_ON
        return self._on

    def add(self, sig: FrameSignals, t: float) -> None:
        dt = DEFAULT_DT if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        speed, on, down = 0.0, False, False
        if sig.face:
            self._observed += dt
            speed = self._head_speed(sig, dt)
            k = dt / (MOUTH_SMOOTH_S + dt)
            self._mouth_ema += k * (sig.mouth_motion - self._mouth_ema)
            on = self._on_screen(sig)
            down = sig.gaze_y - self._center[1] < -LOOK_DOWN
        else:
            self._smooth_pose = None
        self._track_eyes(sig, t, down)
        self._track_yawn(sig, t)
        self._track_gaze(sig.face, on, t, dt)
        still = sig.face and speed < STILL_HEAD_DEG_S and self._mouth_ema < STILL_MOUTH
        self._still = self._still + dt if still else 0.0
        self._frames.append(_Frame(t, sig.face, sig, speed, on, down))
        self._trim(t)

    def _head_speed(self, sig: FrameSignals, dt: float) -> float:
        """deg/s of the smoothed head pose (raw landmarks jitter by a degree or so)."""
        if self._smooth_pose is None or dt <= 0:
            self._smooth_pose = (sig.head_yaw, sig.head_pitch)
            return 0.0
        k = dt / (HEAD_SMOOTH_S + dt)
        yaw0, pitch0 = self._smooth_pose
        yaw, pitch = yaw0 + k * (sig.head_yaw - yaw0), pitch0 + k * (sig.head_pitch - pitch0)
        self._smooth_pose = (yaw, pitch)
        return (abs(yaw - yaw0) + abs(pitch - pitch0)) / dt

    def _track_eyes(self, sig: FrameSignals, t: float, down: bool) -> None:
        if down:  # eyelids look closed when reading the desk: not evidence of sleepiness
            self._closed_since = None
            return
        closed = sig.face and sig.eye_open < BLINK_CLOSED
        if closed and self._closed_since is None:
            self._closed_since = t
        elif not closed and self._closed_since is not None:
            duration = t - self._closed_since
            self._closed_since = None
            if duration >= LONG_CLOSURE_S:
                self._long_closures.append(t)
            else:
                self._blinks.append((t, duration))

    def _track_yawn(self, sig: FrameSignals, t: float) -> None:
        open_wide = sig.face and sig.jaw_open > YAWN_JAW
        if open_wide and self._yawn_since is None:
            self._yawn_since = t
        elif not open_wide and self._yawn_since is not None:
            if t - self._yawn_since >= YAWN_MIN_S:
                self._yawns.append(t)
            self._yawn_since = None

    def _track_gaze(self, face: bool, on: bool, t: float, dt: float) -> None:
        """Look-away episodes with tolerance for brief blips back on screen or face dropouts.

        Absence is never evidence of looking away: a sustained dropout ends the episode.
        """
        if face and not on:
            if self._away_since is None:
                self._away_since = t
            self._back_since = None
            self._away_hold += dt
            return
        if self._away_since is None:
            return
        if self._back_since is None:
            self._back_since, self._back_on = t, face
        if t - self._back_since < BLIP_S:
            return  # maybe just a blip: keep the episode open
        duration = self._back_since - self._away_since
        if self._back_on and GLANCE_MIN_S <= duration <= GLANCE_MAX_S:
            self._glances.append(self._back_since)
        self._away_hold, self._away_since, self._back_since = 0.0, None, None

    def _trim(self, t: float) -> None:
        cutoff = t - MAX_WINDOW_S
        while self._blinks and self._blinks[0][0] < cutoff:
            self._blinks.popleft()
        for dq in (self._long_closures, self._yawns, self._glances):
            while dq and dq[0] < cutoff:
                dq.popleft()
        while self._frames and self._frames[0].t < cutoff:
            self._frames.popleft()

    def features(self, t: float) -> Features:
        def window(seconds: float) -> list[_Frame]:
            return [f for f in self._frames if f.t > t - seconds]

        w10, w30, w60 = window(10), window(30), window(60)
        face10 = [f.s for f in w10 if f.face]
        face30 = [f for f in w30 if f.face]
        sig30 = [f.s for f in face30]
        face60 = [f.s for f in w60 if f.face and not f.down]
        face240 = [f.s for f in self._frames if f.face]
        blinks60 = [d for end, d in self._blinks if end > t - 60]
        span60 = min(60.0, (t - self._frames[0].t) if self._frames else 0.0) or 60.0
        emotion: dict[str, float] = {}
        for s in sig30:
            for k, v in s.emotion.items():
                emotion[k] = emotion.get(k, 0.0) + v / len(sig30)
        return Features(
            t=t,
            face_ratio_10s=len(face10) / len(w10) if w10 else 0.0,
            gaze_on_ratio_30s=_mean([1.0 if f.on else 0.0 for f in face30]),
            gaze_away_hold_s=self._away_hold,
            head_motion_30s=_mean([f.head_speed for f in face30]),
            stillness_s=self._still,
            mouth_motion_10s=_mean([s.mouth_motion for s in face10]),
            blink_rate_per_min_60s=len(blinks60) * 60.0 / span60,
            mean_blink_ms_60s=_mean(blinks60) * 1000.0,
            perclos_60s=_mean([1.0 if s.eye_open < PERCLOS_CLOSED else 0.0 for s in face60]),
            long_closures_90s=sum(1 for e in self._long_closures if e > t - 90),
            yawns_240s=len(self._yawns),
            head_droop_deg_240s=_mean([s.head_pitch for s in face240]),
            head_tilt_10s=_mean([abs(s.head_roll) for s in face10]),
            smile_10s=_mean([s.smile for s in face10]),
            cheek_squint_10s=_mean([s.cheek_squint for s in face10]),
            brow_down_30s=_mean([s.brow_down for s in sig30]),
            brow_inner_up_10s=_mean([s.brow_inner_up for s in face10]),
            mouth_press_30s=_mean([s.mouth_press for s in sig30]),
            glance_away_count_30s=sum(1 for g in self._glances if g > t - 30),
            valence_30s=_mean([s.valence for s in sig30]),
            arousal_30s=_mean([s.arousal for s in sig30]),
            emotion_30s=emotion,
            observed_s=self._observed,
        )
