"""Explainable rules: rolling features + the user's baselines -> a score per face state.

Focused is the background state; see decide(). Each state has a *gate* cue that must be present (so one stray cue never decides a state)
and supporting cues. value = gate x mean(all cues), plus the user's correction bias.
Thresholds are relative to the user's own baseline wherever a baseline exists; slow states
use stricter thresholds until the baselines are warm.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from moodmusic.mood.baselines import PersonalBaselines
from moodmusic.mood.features import Features
from moodmusic.mood.states import EVIDENCE_WINDOW_S, FaceState as F

DECIDE_MIN = 0.6
DECIDE_MARGIN = 0.1
COLD_FACTOR = 1.5  # slow-state thresholds while baselines are not warm
REASON_MIN = 0.5
SAD_EXPLAINED_PENALTY = 0.3
DOMINATED_PENALTY = 0.3
# More specific state first: when it is confidently present, the general one steps back.
DOMINATES = [(F.EXCITED, F.HAPPY), (F.SLEEPY, F.TIRED), (F.TIRED, F.SAD), (F.FOCUSED, F.SAD)]


@dataclass(frozen=True)
class Score:
    value: float
    reasons: list[str] = field(default_factory=list)


def ramp(x: float, lo: float, hi: float) -> float:
    """0 at/below lo, 1 at/above hi, linear between (hi < lo inverts)."""
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


class _Cues:
    def __init__(self) -> None:
        self.values: list[float] = []
        self.reasons: list[str] = []

    def add(self, value: float, reason: str = "") -> float:
        self.values.append(value)
        if reason and value >= REASON_MIN:
            self.reasons.append(reason)
        return value

    def score(self, gate: float) -> Score:
        mean = sum(self.values) / len(self.values) if self.values else 0.0
        return Score(gate * mean, self.reasons if gate > 0 else [])


def _mouth_quiet(f: Features) -> float:
    return 1 - ramp(f.mouth_motion_10s, 0.01, 0.05)


def _focused(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    gate = c.add(ramp(f.gaze_on_ratio_30s, 0.6, 0.85), "eyes on the screen")
    hm = b.get("head_motion_30s")
    c.add(1 - ramp(f.head_motion_30s, hm, hm * 2 + 2), "head steady")
    frown = ramp(f.brow_down_30s, b.get("brow_down_30s"), b.get("brow_down_30s") + 0.2)
    c.add(0.5 + 0.5 * frown, "concentrating frown" if frown >= REASON_MIN else "")
    c.add(_mouth_quiet(f), "not talking")
    angry = f.emotion_30s.get("anger", 0.0) + f.emotion_30s.get("disgust", 0.0)
    c.add(1 - ramp(angry, 0.2, 0.4))
    return c.score(gate)


def _deep_thought(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    away = c.add(ramp(f.gaze_away_hold_s, 8, 30), f"looking away {int(f.gaze_away_hold_s)} s")
    c.add(ramp(f.stillness_s, 5, 20), "very still")
    c.add(1 - ramp(abs(f.valence_30s), 0.3, 0.5), "calm face")
    c.add(_mouth_quiet(f), "quiet")
    present = ramp(f.face_ratio_10s, 0.8, 0.9)
    return c.score(away * present)


def _love(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    soft = ramp(f.smile_10s, 0.1, 0.2) * (1 - ramp(f.smile_10s, 0.5, 0.65))
    c.add(soft, "soft smile")
    c.add(ramp(f.glance_away_count_30s, 0, 2), "shy glances away")
    c.add(ramp(f.head_tilt_10s, 3, 8), "head tilted")
    c.add(ramp(f.valence_30s, 0.0, 0.3), "warm expression")
    return c.score(soft)


def _happy(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    smile = c.add(ramp(f.smile_10s, 0.3, 0.5), "smiling")
    c.add(ramp(f.cheek_squint_10s, 0.15, 0.3), "eyes smiling too")
    c.add(ramp(f.valence_30s, 0.1, 0.3), "positive")
    return c.score(smile)


def _excited(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    big = max(ramp(f.smile_10s, 0.55, 0.75), ramp(f.brow_inner_up_10s, 0.2, 0.4))
    c.add(big, "big smile / raised brows")
    c.add(ramp(f.arousal_30s, 0.2, 0.4), "high energy")
    hm = b.get("head_motion_30s")
    c.add(ramp(f.head_motion_30s, hm, hm * 2), "lively")
    return c.score(big)


def _tired(f: Features, b: PersonalBaselines, k: float) -> Score:
    c = _Cues()
    blink_ratio = f.mean_blink_ms_60s / max(b.get("mean_blink_ms_60s"), 1e-6)
    slow = c.add(ramp(blink_ratio, 1.3 * k, 1.3 * k + 0.4), "slow blinks")
    closed_ratio = f.perclos_60s / max(b.get("perclos_60s"), 1e-6)
    heavy = c.add(ramp(closed_ratio, 2 * k, 2 * k + 2), "heavy eyelids")
    c.add(ramp(b.get("head_droop_deg_240s") - f.head_droop_deg_240s, 5 * k, 5 * k + 5),
          "head drooping")
    c.add(1 - ramp(f.arousal_30s, -0.2, 0.0), "low energy")
    return c.score(max(slow, heavy))


def _sleepy(f: Features, b: PersonalBaselines, k: float) -> Score:
    c = _Cues()
    closures = c.add(ramp(f.long_closures_90s, k, 2 * k), "eyes closing")
    yawns = c.add(ramp(f.yawns_240s, 0, k), "yawning")
    closed_ratio = f.perclos_60s / max(b.get("perclos_60s"), 1e-6)
    c.add(ramp(closed_ratio, 2 * k, 4 * k), "heavy eyelids")
    return c.score(max(closures, yawns))


def _stressed(f: Features, b: PersonalBaselines, k: float) -> Score:
    c = _Cues()
    brow = c.add(ramp(f.brow_down_30s - b.get("brow_down_30s"), 0.05 * k, 0.15 * k),
                 "tense brow")
    press = c.add(ramp(f.mouth_press_30s - b.get("mouth_press_30s"), 0.05 * k, 0.15 * k),
                  "pressed lips")
    worried = c.add(ramp(f.brow_inner_up_10s, 0.2 * k, 0.4 * k), "worried brow")
    hm = b.get("head_motion_30s")
    restless = ramp(f.head_motion_30s / max(hm, 1e-6), 1.5 * k, 2.5 * k)
    unsettled = c.add(max(restless, ramp(-f.valence_30s, 0.2, 0.4)), "restless / uneasy")
    tension = sum(x >= REASON_MIN for x in (brow, press, worried))
    gate = 1.0 if tension >= 2 and unsettled >= REASON_MIN else 0.0
    return c.score(gate)


def _bored(f: Features, b: PersonalBaselines, k: float) -> Score:
    c = _Cues()
    drift = ramp(b.get("gaze_on_ratio_30s") - f.gaze_on_ratio_30s, 0.2 * k, 0.4 * k)
    wander = c.add(drift * ramp(f.glance_away_count_30s, 1, 4), "eyes wandering")
    c.add(1 - ramp(f.smile_10s - b.get("smile_10s"), 0.05, 0.15), "flat expression")
    eyes_closing = ramp(f.long_closures_90s, k, 2 * k)
    c.add(ramp(f.yawns_240s, 0, k) * (1 - eyes_closing), "yawning")
    c.add(ramp(b.get("head_droop_deg_240s") - f.head_droop_deg_240s, 3 * k, 8 * k), "slumped")
    sustained_look = ramp(f.gaze_away_hold_s, 8, 20)  # one long stare is thought, not boredom
    return c.score(wander * (1 - sustained_look))


def _sad(f: Features, b: PersonalBaselines) -> Score:
    c = _Cues()
    low = c.add(ramp(-f.valence_30s, 0.3, 0.5), "looking down")
    c.add(1 - ramp(f.arousal_30s, -0.1, 0.1), "low energy")
    return c.score(low)


def score_states(f: Features, b: PersonalBaselines,
                 bias: dict[F, float] | None = None) -> dict[F, Score]:
    k = 1.0 if b.warm else COLD_FACTOR
    scores = {
        F.FOCUSED: _focused(f, b), F.DEEP_THOUGHT: _deep_thought(f, b), F.LOVE: _love(f, b),
        F.HAPPY: _happy(f, b), F.EXCITED: _excited(f, b), F.TIRED: _tired(f, b, k),
        F.SLEEPY: _sleepy(f, b, k), F.STRESSED: _stressed(f, b, k), F.BORED: _bored(f, b, k),
        F.SAD: _sad(f, b),
    }
    for state, window in EVIDENCE_WINDOW_S.items():  # slow states need sustained evidence
        if f.observed_s < window:
            scores[state] = Score(0.0, [])
    for strong, weak in DOMINATES:  # e.g. sadness explained by tiredness or focus
        if scores[strong].value >= DECIDE_MIN:
            w = scores[weak]
            scores[weak] = Score(max(0.0, w.value - DOMINATED_PENALTY), w.reasons)
    if bias:
        scores = {s: Score(max(0.0, min(1.0, sc.value + bias.get(s, 0.0))), sc.reasons)
                  for s, sc in scores.items()}
    return scores


def decide(scores: dict[F, Score], current: F | None) -> tuple[F | None, str]:
    """Pick a state, or (None, "") to hold the current one.

    Focused is the background state of working at a desk: any other state that is confident
    and clearly ahead of the other non-focused states wins over it. Focused applies when no
    other state is clear but the focus cues are.
    """
    others = sorted(((s, sc) for s, sc in scores.items() if s != F.FOCUSED),
                    key=lambda kv: kv[1].value, reverse=True)
    if others:
        best, top = others[0]
        runner = others[1][1].value if len(others) > 1 else 0.0
        if top.value >= DECIDE_MIN and top.value - runner >= DECIDE_MARGIN:
            return best, ", ".join(top.reasons[:2])
    focus = scores.get(F.FOCUSED)
    if focus is not None and focus.value >= DECIDE_MIN:
        return F.FOCUSED, ", ".join(focus.reasons[:2])
    return None, ""
