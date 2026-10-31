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
STILL_HEAD_DEG_S = 3.0
STILL_MOUTH = 0.02
GLANCE_MAX_S = 3.0


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
        self._prev_face: FrameSignals | None = None
        self._prev_face_t: float | None = None
        self._closed_since: float | None = None
        self._yawn_since: float | None = None
        self._away_since: float | None = None
        self._away_hold = 0.0
        self._still = 0.0
        self._observed = 0.0

    def add(self, sig: FrameSignals, t: float) -> None:
        dt = DEFAULT_DT if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        speed = 0.0
        if sig.face:
            self._observed += dt
            if self._prev_face is not None and self._prev_face_t is not None:
                gap = t - self._prev_face_t
                if gap > 0:
                    speed = (abs(sig.head_yaw - self._prev_face.head_yaw)
                             + abs(sig.head_pitch - self._prev_face.head_pitch)) / gap
            self._prev_face, self._prev_face_t = sig, t
        self._track_eyes(sig, t)
        self._track_yawn(sig, t)
        self._track_gaze(sig, t, dt)
        still = sig.face and speed < STILL_HEAD_DEG_S and sig.mouth_motion < STILL_MOUTH
        self._still = self._still + dt if still else 0.0
        self._frames.append(_Frame(t, sig.face, sig, speed))
        self._trim(t)

    def _track_eyes(self, sig: FrameSignals, t: float) -> None:
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

    def _track_gaze(self, sig: FrameSignals, t: float, dt: float) -> None:
        if not sig.face:  # absence is not looking away
            self._away_hold, self._away_since = 0.0, None
            return
        if not sig.gaze_on_screen:
            self._away_hold += dt
            if self._away_since is None:
                self._away_since = t
            return
        if self._away_since is not None and t - self._away_since <= GLANCE_MAX_S:
            self._glances.append(t)
        self._away_hold, self._away_since = 0.0, None

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
        face60 = [f.s for f in w60 if f.face]
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
            gaze_on_ratio_30s=_mean([1.0 if s.gaze_on_screen else 0.0 for s in sig30]),
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
