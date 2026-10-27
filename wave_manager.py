"""
wave_manager.py — Progressive Wave System and Adaptive Difficulty Controller.

Design principles
─────────────────
• Gameplay is NEVER paused. Spawning, target physics, gesture recognition,
  mascot, audio, and HUD all run every frame regardless of wave state.
• Wave transitions are INSTANT: the new config is applied immediately when the
  objective is reached; no INTRO or RECOVERY blocking phase exists.
• A small toast notification is shown for TOAST_DURATION seconds (≤ 0.8s).
  The toast is purely cosmetic — it never gates any gameplay logic.
• Difficulty adapts at wave boundaries only, within tight clamped limits.
• Camera loss is never counted as a player miss.

Speed values are tuned for a 1280×720 window (user-specified 1600×900 reference
values scaled by 720/900 = 0.8).
"""

from __future__ import annotations

import collections
import math
import random
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Deque, Optional


# ---------------------------------------------------------------------------
# Wave parameter table
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WaveConfig:
    wave: int
    max_targets: int        # max simultaneously on screen
    fall_speed: float       # px/s  (applied to every newly spawned target)
    spawn_interval: float   # seconds between spawn attempts
    objective_count: int    # targets destroyed to complete this wave


# Tuned for 1280×720 with faster, more exciting progression
WAVE_TABLE: list[WaveConfig] = [
    WaveConfig(1,  2, 235, 1.20, 10),
    WaveConfig(2,  2, 275, 1.00, 12),
    WaveConfig(3,  3, 315, 0.88, 14),
    WaveConfig(4,  3, 355, 0.78, 16),
    WaveConfig(5,  3, 390, 0.70, 18),
    WaveConfig(6,  3, 415, 0.65, 20),
    WaveConfig(7,  4, 435, 0.60, 22),
    WaveConfig(8,  4, 450, 0.58, 24),
    WaveConfig(9,  4, 465, 0.55, 26),
    WaveConfig(10, 4, 480, 0.55, 28),
]

# Hard caps — nothing ever exceeds these
HARD_MAX_SPEED    = 520.0   # px/s
HARD_MIN_INTERVAL = 0.50    # s
HARD_MAX_TARGETS  = 4

# Toast notification duration (seconds). Pure cosmetic; never blocks gameplay.
TOAST_DURATION = 0.70


# ---------------------------------------------------------------------------
# Dynamic wave generator for wave 11+
# ---------------------------------------------------------------------------
def _generate_wave(n: int) -> WaveConfig:
    base  = WAVE_TABLE[-1]
    extra = n - len(WAVE_TABLE)
    speed    = min(base.fall_speed + extra * 4, HARD_MAX_SPEED)
    interval = max(base.spawn_interval - extra * 0.01, HARD_MIN_INTERVAL)
    obj      = base.objective_count + extra * 2
    max_t    = min(base.max_targets + (extra // 5), HARD_MAX_TARGETS)
    return WaveConfig(
        wave=n,
        max_targets=max_t,
        fall_speed=round(speed, 1),
        spawn_interval=round(interval, 3),
        objective_count=obj,
    )


def get_wave_config(wave: int) -> WaveConfig:
    if wave <= len(WAVE_TABLE):
        return WAVE_TABLE[wave - 1]
    return _generate_wave(wave)


# ---------------------------------------------------------------------------
# Performance tracking (rolling window, adaptive difficulty)
# ---------------------------------------------------------------------------
class Outcome(Enum):
    HIT  = auto()
    MISS = auto()


@dataclass
class _OutcomeRecord:
    outcome: Outcome
    timestamp: float


class PerformanceTracker:
    WINDOW = 12

    def __init__(self) -> None:
        self._history: Deque[_OutcomeRecord] = collections.deque(maxlen=self.WINDOW)
        self.longest_combo: int = 0
        self._current_combo: int = 0
        self.total_hits: int = 0
        self.total_misses: int = 0

    def reset(self) -> None:
        self._history.clear()
        self.longest_combo = 0
        self._current_combo = 0
        self.total_hits = 0
        self.total_misses = 0

    def record_hit(self) -> None:
        self._history.append(_OutcomeRecord(Outcome.HIT, time.monotonic()))
        self._current_combo += 1
        self.longest_combo = max(self.longest_combo, self._current_combo)
        self.total_hits += 1

    def record_miss(self) -> None:
        self._history.append(_OutcomeRecord(Outcome.MISS, time.monotonic()))
        self._current_combo = 0
        self.total_misses += 1

    @property
    def window_hit_rate(self) -> float:
        if len(self._history) < 3:
            return 0.5
        hits = sum(1 for r in self._history if r.outcome == Outcome.HIT)
        return hits / len(self._history)

    @property
    def has_enough_data(self) -> bool:
        return len(self._history) >= 5

    @property
    def current_combo(self) -> int:
        return self._current_combo


class PerfClass(Enum):
    HIGH       = auto()
    NORMAL     = auto()
    STRUGGLING = auto()


def classify_performance(tracker: PerformanceTracker) -> PerfClass:
    if not tracker.has_enough_data:
        return PerfClass.NORMAL
    hr = tracker.window_hit_rate
    if hr >= 0.80:
        return PerfClass.HIGH
    if hr <= 0.45:
        return PerfClass.STRUGGLING
    return PerfClass.NORMAL


# ---------------------------------------------------------------------------
# Difficulty controller (bounded adaptive bias applied at wave boundaries)
# ---------------------------------------------------------------------------
class DifficultyController:
    SPEED_STEP    = 0.06   # ±6% per wave boundary
    INTERVAL_STEP = 0.06
    MAX_BOOST     = 0.20   # hard cap: never more than +20% over base
    MAX_EASE      = 0.15   # hard cap: never less than –15% under base

    def __init__(self) -> None:
        self._speed_bias: float    = 0.0
        self._interval_bias: float = 0.0

    def reset(self) -> None:
        self._speed_bias    = 0.0
        self._interval_bias = 0.0

    def evaluate(self, perf: PerfClass) -> None:
        if perf == PerfClass.HIGH:
            self._speed_bias    = min(self._speed_bias    + self.SPEED_STEP, self.MAX_BOOST)
            self._interval_bias = max(self._interval_bias - self.INTERVAL_STEP, -self.MAX_BOOST)
        elif perf == PerfClass.STRUGGLING:
            self._speed_bias    = max(self._speed_bias    - self.SPEED_STEP, -self.MAX_EASE)
            self._interval_bias = min(self._interval_bias + self.INTERVAL_STEP, self.MAX_EASE)
        # NORMAL → no change

    def apply(self, cfg: WaveConfig) -> WaveConfig:
        """Return a WaveConfig with adaptive bias applied (clamped to hard limits)."""
        speed    = min(cfg.fall_speed    * (1.0 + self._speed_bias),    HARD_MAX_SPEED)
        interval = max(cfg.spawn_interval * (1.0 + self._interval_bias), HARD_MIN_INTERVAL)
        return WaveConfig(
            wave=cfg.wave,
            max_targets=cfg.max_targets,
            fall_speed=round(speed, 1),
            spawn_interval=round(interval, 3),
            objective_count=cfg.objective_count,
        )


# ---------------------------------------------------------------------------
# Gesture sequencer
# ---------------------------------------------------------------------------
_ALL_GESTURES = [
    "open_palm", "closed_fist", "thumbs_up",
    "thumbs_down", "peace_sign", "index_up",
]


class GestureSequencer:
    """Selects varied gestures, avoiding immediate repetition."""

    def __init__(self) -> None:
        self._recent: Deque[str] = collections.deque(maxlen=3)
        self._rng = random.Random()

    def seed(self, s: int) -> None:
        self._rng.seed(s)

    def next_gesture(self, exclude: Optional[set[str]] = None) -> str:
        avoid    = set(self._recent) | (exclude or set())
        filtered = [g for g in _ALL_GESTURES if g not in avoid]
        if not filtered:
            filtered = list(_ALL_GESTURES)
        gesture = self._rng.choice(filtered)
        self._recent.append(gesture)
        return gesture


# ---------------------------------------------------------------------------
# Toast notification (purely cosmetic, non-blocking)
# ---------------------------------------------------------------------------
@dataclass
class WaveToast:
    """Transient overlay shown for TOAST_DURATION seconds.  Never blocks gameplay."""
    text: str  = ""
    sub:  str  = ""
    timer: float = 0.0    # counts UP; hidden when >= TOAST_DURATION
    active: bool = False

    def start(self, text: str, sub: str) -> None:
        self.text   = text
        self.sub    = sub
        self.timer  = 0.0
        self.active = True

    def update(self, dt: float) -> None:
        if self.active:
            self.timer += dt
            if self.timer >= TOAST_DURATION:
                self.active = False

    @property
    def alpha_fraction(self) -> float:
        """1.0 when freshly started, fades to 0.0 over the last 30% of duration."""
        if not self.active:
            return 0.0
        fade_start = TOAST_DURATION * 0.70
        if self.timer <= fade_start:
            return 1.0
        return max(0.0, 1.0 - (self.timer - fade_start) / (TOAST_DURATION - fade_start))


# ---------------------------------------------------------------------------
# Wave events emitted each frame (read by main.py for audio triggers)
# ---------------------------------------------------------------------------
@dataclass
class WaveEvent:
    wave_complete: bool = False


# ---------------------------------------------------------------------------
# WaveManager
# ---------------------------------------------------------------------------
class WaveManager:
    """
    Tracks wave number, objectives, adaptive difficulty, and toast notifications.

    Key contract:
      • `is_active` and `spawning_allowed` are ALWAYS True once reset() is called.
      • Wave transitions are INSTANT (no pausing phases).
      • Toast is a read-only cosmetic property for UIRenderer; it has no effect on logic.
    """

    def __init__(self) -> None:
        self.perf  = PerformanceTracker()
        self.diff  = DifficultyController()
        self.seq   = GestureSequencer()
        self.toast = WaveToast()
        self.event = WaveEvent()

        self._wave_number: int     = 1
        self._current_cfg: WaveConfig = get_wave_config(1)
        self._destroyed_this_wave: int = 0

        # Compatibility shim: ui.py reads these for the large-banner path
        # They are always empty / False in this implementation.
        self.show_banner: bool = False
        self.banner_text: str  = ""
        self.banner_sub:  str  = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Call at the start of every new game run."""
        self.perf.reset()
        self.diff.reset()
        self.seq.seed(int(time.monotonic() * 1_000_000) % 100_000)
        self._wave_number         = 1
        self._current_cfg         = self.diff.apply(get_wave_config(1))
        self._destroyed_this_wave = 0
        self.event                = WaveEvent()
        self.show_banner          = False
        self.banner_text          = ""
        self.banner_sub           = ""
        self.toast.start(f"WAVE  1", "Get ready!")
        self.toast.active = True

    # ------------------------------------------------------------------
    # Frame update — call every frame with dt seconds
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.event = WaveEvent()
        self.toast.update(dt)

        # Check objective completion (instant transition — no blocking phase)
        if self._destroyed_this_wave >= self._current_cfg.objective_count:
            self._advance_wave()

    # ------------------------------------------------------------------
    # Hit / miss recording
    # ------------------------------------------------------------------

    def record_hit(self) -> None:
        self.perf.record_hit()
        self._destroyed_this_wave += 1

    def record_miss(self, camera_ok: bool = True) -> None:
        if camera_ok:
            self.perf.record_miss()

    # ------------------------------------------------------------------
    # Gesture selection
    # ------------------------------------------------------------------

    def next_gesture(self, exclude: Optional[set[str]] = None) -> str:
        return self.seq.next_gesture(exclude=exclude)

    # ------------------------------------------------------------------
    # Properties read by GameState and UIRenderer
    # ------------------------------------------------------------------

    @property
    def wave_number(self) -> int:
        return self._wave_number

    @property
    def is_active(self) -> bool:
        """Always True — gameplay is never paused by the wave system."""
        return True

    @property
    def spawning_allowed(self) -> bool:
        """Always True — spawning is never blocked by wave transitions."""
        return True

    @property
    def max_targets(self) -> int:
        return self._current_cfg.max_targets

    @property
    def fall_speed(self) -> float:
        return self._current_cfg.fall_speed

    @property
    def spawn_interval(self) -> float:
        return self._current_cfg.spawn_interval

    @property
    def objective_count(self) -> int:
        return self._current_cfg.objective_count

    @property
    def destroyed_this_wave(self) -> int:
        return self._destroyed_this_wave

    @property
    def progress_fraction(self) -> float:
        obj = max(1, self._current_cfg.objective_count)
        return min(1.0, self._destroyed_this_wave / obj)

    # ------------------------------------------------------------------
    # Internal: instant wave advance
    # ------------------------------------------------------------------

    def _advance_wave(self) -> None:
        # Evaluate rolling performance and adjust bias for next wave
        perf_class = classify_performance(self.perf)
        self.diff.evaluate(perf_class)

        self._wave_number         += 1
        raw_cfg                    = get_wave_config(self._wave_number)
        self._current_cfg          = self.diff.apply(raw_cfg)
        self._destroyed_this_wave  = 0
        self.event.wave_complete   = True

        # Show a short non-blocking toast
        sub = "INTENSE!" if self._wave_number > 5 else "Keep going!"
        self.toast.start(f"WAVE  {self._wave_number}", sub)
