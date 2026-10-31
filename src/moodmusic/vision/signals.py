"""Per-frame numeric face signals: gaze, head pose, eyes, mouth, emotion. Numbers only."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from moodmusic.vision.types import EmotionReading, FaceObservation

# MediaPipe FaceMesh indices (subject's right eye is on the image's left).
EYE_R_OUT, EYE_R_IN, EYE_L_IN, EYE_L_OUT = 33, 133, 362, 263
NOSE, CHIN, IRIS_R, IRIS_L = 1, 152, 468, 473
FOREHEAD, BRIDGE = 10, 168  # neither moves with the jaw
GAZE_ON_LIMIT = 0.35
YAW_ON_LIMIT_DEG = 25.0


@dataclass(frozen=True)
class FrameSignals:
    face: bool = False
    gaze_x: float = 0.0  # -1..1, + = image-right
    gaze_y: float = 0.0  # -1..1, + = up
    gaze_on_screen: bool = False
    head_yaw: float = 0.0  # degrees, + = nose toward image-right
    head_pitch: float = 0.0  # degrees, + = up
    head_roll: float = 0.0  # degrees
    eye_open: float = 0.0  # 0..1
    smile: float = 0.0
    cheek_squint: float = 0.0
    brow_down: float = 0.0
    brow_inner_up: float = 0.0
    mouth_press: float = 0.0
    jaw_open: float = 0.0
    mouth_close: float = 0.0
    mouth_motion: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    emotion: dict[str, float] = field(default_factory=dict)


def _mean(b: dict[str, float], *keys: str) -> float:
    return sum(b.get(k, 0.0) for k in keys) / len(keys)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _head_pose(p) -> tuple[float, float, float]:
    """Yaw from the nose vs the eye corners; pitch from the forehead-to-nose-bridge line in
    3D (both rigid, so talking or yawning doesn't move it); roll from the eye line."""
    mid_x = (p[EYE_R_OUT][0] + p[EYE_L_OUT][0]) / 2
    half = abs(p[EYE_L_OUT][0] - p[EYE_R_OUT][0]) / 2
    yaw = math.degrees(math.asin(_clamp((p[NOSE][0] - mid_x) / half))) if half > 1e-6 else 0.0
    up_y = p[BRIDGE][1] - p[FOREHEAD][1]  # > 0 when the forehead is above the bridge
    dz = p[FOREHEAD][2] - p[BRIDGE][2]  # > 0 when the forehead leans away (chin up)
    pitch = math.degrees(math.atan2(dz, up_y)) if abs(up_y) > 1e-6 or abs(dz) > 1e-6 else 0.0
    roll = math.degrees(math.atan2(p[EYE_L_OUT][1] - p[EYE_R_OUT][1],
                                   p[EYE_L_OUT][0] - p[EYE_R_OUT][0]))
    return yaw, pitch, roll


def _iris_offset(p, iris: int, a: int, b: int) -> tuple[float, float]:
    cx, cy = (p[a][0] + p[b][0]) / 2, (p[a][1] + p[b][1]) / 2
    half = abs(p[b][0] - p[a][0]) / 2
    if half < 1e-6:
        return 0.0, 0.0
    return _clamp((p[iris][0] - cx) / half), _clamp(-(p[iris][1] - cy) / half)


def _gaze(p, b: dict[str, float]) -> tuple[float, float]:
    if p is not None and len(p) > IRIS_L:
        rx, ry = _iris_offset(p, IRIS_R, EYE_R_OUT, EYE_R_IN)
        lx, ly = _iris_offset(p, IRIS_L, EYE_L_IN, EYE_L_OUT)
        return (rx + lx) / 2, (ry + ly) / 2
    # Fallback: blendshapes (subject's left eye looking out = image-right).
    gx = _mean(b, "eyeLookOutLeft", "eyeLookInRight") - _mean(b, "eyeLookInLeft", "eyeLookOutRight")
    gy = _mean(b, "eyeLookUpLeft", "eyeLookUpRight") - _mean(b, "eyeLookDownLeft", "eyeLookDownRight")
    return _clamp(gx), _clamp(gy)


def extract_signals(obs: FaceObservation, reading: EmotionReading | None,
                    prev: FrameSignals | None) -> FrameSignals:
    if obs.face_count == 0:
        return FrameSignals()
    b = obs.blendshapes
    p = obs.landmarks
    if p is not None:  # pixel units (x, y and z by width), plain floats
        w, h = obs.image_size or (1, 1)
        p = [(float(x) * w, float(y) * h, float(z) * w) for x, y, z in p.tolist()]
    yaw, pitch, roll = _head_pose(p) if p is not None and len(p) > CHIN else (0.0, 0.0, 0.0)
    gx, gy = _gaze(p, b)
    jaw, close = b.get("jawOpen", 0.0), b.get("mouthClose", 0.0)
    motion = 0.0
    if prev is not None and prev.face:
        motion = abs(jaw - prev.jaw_open) + abs(close - prev.mouth_close)
    return FrameSignals(
        face=True,
        gaze_x=gx, gaze_y=gy,
        gaze_on_screen=abs(gx) < GAZE_ON_LIMIT and abs(gy) < GAZE_ON_LIMIT
        and abs(yaw) < YAW_ON_LIMIT_DEG,
        head_yaw=yaw, head_pitch=pitch, head_roll=roll,
        eye_open=1.0 - _mean(b, "eyeBlinkLeft", "eyeBlinkRight"),
        smile=_mean(b, "mouthSmileLeft", "mouthSmileRight"),
        cheek_squint=_mean(b, "cheekSquintLeft", "cheekSquintRight"),
        brow_down=_mean(b, "browDownLeft", "browDownRight"),
        brow_inner_up=b.get("browInnerUp", 0.0),
        mouth_press=_mean(b, "mouthPressLeft", "mouthPressRight"),
        jaw_open=jaw, mouth_close=close, mouth_motion=motion,
        valence=reading.valence if reading else 0.0,
        arousal=reading.arousal if reading else 0.0,
        emotion=dict(reading.probs) if reading else {},
    )
