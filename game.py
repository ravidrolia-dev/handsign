"""
game.py — Core game logic: spawning, scoring, difficulty, gesture matching,
life management.

GameState is created once and reset() is called at the start of each new game.
update() is called once per Pygame frame.

Wave system integration:
  - GameState owns a WaveManager instance.
  - Spawn parameters (speed, interval, max targets) come from WaveManager.
  - Hits and misses are reported to WaveManager for adaptive tracking.
  - main.py reads game.wave_manager to update audio and UI.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass

import settings as S
import audio_manager
from hand_tracker import SharedGestureState, GestureFrame
from target import FallingTarget, TargetState
from wave_manager import WaveManager


# ---------------------------------------------------------------------------
# Stability tracker — ensures a gesture is held for STABILITY_DURATION
# before it counts as "detected"
# ---------------------------------------------------------------------------

@dataclass
class _StabilityState:
    last_gesture: str | None = None
    hold_time: float = 0.0

    def update(self, new_gesture: str | None, dt: float) -> bool:
        """
        Returns True when the gesture has been held long enough.
        Resets timer on any change.
        """
        if new_gesture != self.last_gesture:
            self.last_gesture = new_gesture
            self.hold_time = 0.0
            return False
        if new_gesture is None:
            return False
        self.hold_time += dt
        return self.hold_time >= S.STABILITY_DURATION


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    """
    Central game state. Call reset() before each new game, update() each frame.
    """

    def __init__(self, shared_gesture: SharedGestureState) -> None:
        self._shared = shared_gesture

        # Wave progression and adaptive difficulty
        self.wave_manager = WaveManager()

        # Stable game state (set by reset)
        self._lives: int = S.INITIAL_LIVES
        self._score: int = 0
        self._combo: int = 0
        self._best_score: int = self._load_best_score()

        self._active_targets: list[FallingTarget] = []
        self._spawn_timer: float = 0.0
        self._last_match_time: float = 0.0
        self._stability = _StabilityState()

        # Track previous gesture frame timestamp to avoid double-firing
        self._last_frame_ts: float = 0.0

        # Events that main.py can read this frame
        self.life_lost_this_frame: bool = False
        self.target_destroyed_this_frame: bool = False

    def reset(self) -> None:
        """Prepare for a fresh game run."""
        self.wave_manager.reset()
        self._lives = S.INITIAL_LIVES
        self._score = 0
        self._combo = 0
        self._active_targets = []
        self._spawn_timer = 0.0
        self._last_match_time = 0.0
        self._stability = _StabilityState()
        self._last_frame_ts = 0.0
        self.life_lost_this_frame = False
        self.target_destroyed_this_frame = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def lives(self) -> int:
        return self._lives

    @property
    def score(self) -> int:
        return self._score

    @property
    def combo(self) -> int:
        return self._combo

    @property
    def best_score(self) -> int:
        return self._best_score

    @property
    def active_targets(self) -> list[FallingTarget]:
        return self._active_targets

    @property
    def is_game_over(self) -> bool:
        return self._lives <= 0

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Called once per frame. dt is seconds since last frame."""
        self.life_lost_this_frame = False
        self.target_destroyed_this_frame = False

        # 0. Tick the wave manager first so phase/banner state is up-to-date
        self.wave_manager.update(dt)

        # 1. Read gesture from background thread
        frame: GestureFrame = self._shared.read()
        camera_ok: bool = frame.camera_ok

        # 2. Update stability tracker
        stable = self._stability.update(frame.gesture, dt)

        # 3. Gesture matching — only during ACTIVE wave phase
        if (
            self.wave_manager.is_active
            and stable
            and frame.gesture is not None
            and frame.confidence >= S.CONFIDENCE_THRESHOLD
        ):
            now = time.monotonic()
            if now - self._last_match_time >= S.GESTURE_COOLDOWN:
                self._check_gesture_match(frame.gesture, frame.confidence)

        # 4. Update all targets
        newly_missed = []
        still_active: list[FallingTarget] = []
        for t in self._active_targets:
            t.update(dt)
            if t.state == TargetState.MISSED and t not in newly_missed:
                newly_missed.append(t)
            if not t.is_done:
                still_active.append(t)

        # Process misses (subtract lives, reset combo)
        for t in newly_missed:
            if t.state == TargetState.MISSED:
                self._lives = max(0, self._lives - 1)
                self._combo = 0
                self.life_lost_this_frame = True
                self.wave_manager.record_miss(camera_ok=camera_ok)
                audio_manager.play_sfx("life_lost")
                if self._lives == 1:
                    audio_manager.play_sfx("low_health")

        self._active_targets = still_active

        # Check danger zone proximity for warning SFX
        for t in self._active_targets:
            if t.is_alive and (t.y + t._size // 2 > t._danger_y - 75):
                audio_manager.play_sfx("danger_warning")
                break

        # 5. Spawn timer — only during ACTIVE wave phase
        if self.wave_manager.spawning_allowed:
            self._spawn_timer += dt
            self._try_spawn()

    def draw(self, surface: "pygame.Surface") -> None:  # type: ignore[name-defined]
        """Draw all active targets onto the given surface."""
        for t in self._active_targets:
            t.draw(surface)

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def _try_spawn(self) -> None:
        """
        Spawn one new target if:
          - spawn_timer has elapsed
          - active target count is below wave max_targets
        """
        wm = self.wave_manager
        if self._spawn_timer < wm.spawn_interval:
            return
        if len(self._active_targets) >= wm.max_targets:
            self._spawn_timer = 0.0
            return

        self._spawn_timer = 0.0

        # Choose lane with fewest active falling targets; break ties randomly
        lane_counts = [0] * S.LANE_COUNT
        for t in self._active_targets:
            if t.is_alive:
                lane_counts[t.lane] += 1

        min_count = min(lane_counts)
        candidates_lanes = [i for i, c in enumerate(lane_counts) if c == min_count]
        lane = random.choice(candidates_lanes)

        # Avoid repeating a gesture already in that lane
        occupied_gestures = {
            t.gesture_name
            for t in self._active_targets
            if t.is_alive and t.lane == lane
        }
        # Use wave sequencer for gesture variety
        gesture = wm.next_gesture(exclude=occupied_gestures if occupied_gestures else None)

        x = float(S.LANE_X[lane])
        start_y = float(-S.TARGET_SIZE // 2)

        target = FallingTarget(
            gesture_name=gesture,
            lane=lane,
            x=x,
            start_y=start_y,
            fall_speed=wm.fall_speed,
        )
        self._active_targets.append(target)
        audio_manager.play_sfx("target_spawn")

    # ------------------------------------------------------------------
    # Gesture matching
    # ------------------------------------------------------------------

    def _check_gesture_match(self, gesture: str, confidence: float) -> None:
        """
        Destroy at most ONE active target matching the gesture.
        Prefers the target closest to the danger line (highest y).
        """
        now = time.monotonic()

        matching: list[FallingTarget] = [
            t for t in self._active_targets
            if t.is_alive and t.gesture_name == gesture
        ]
        if not matching:
            return

        # Target closest to danger line (largest y) gets destroyed first
        target = max(matching, key=lambda t: t.y)
        target.destroy()
        audio_manager.play_sfx("gesture_detected")
        audio_manager.play_sfx("target_hit")

        # Notify wave manager
        self.wave_manager.record_hit()

        # Score: wave number boosts base points slightly
        old_score = self._score
        wave_bonus_pts = S.POINTS_PER_TARGET + (self.wave_manager.wave_number - 1) * 2
        bonus = int(wave_bonus_pts * self._combo * S.COMBO_MULTIPLIER)
        self._score += wave_bonus_pts + bonus
        self._combo += 1
        self._last_match_time = now
        self.target_destroyed_this_frame = True

        if self._combo >= 2:
            audio_manager.play_sfx("combo")

        if (self._score // 100) > (old_score // 100):
            audio_manager.play_sfx("level_up")

        # Update best score
        if self._score > self._best_score:
            self._best_score = self._score
            self._save_best_score()

        # Reset stability so held gesture doesn't immediately clear another target
        self._stability = _StabilityState()

    def _get_save_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), S.HIGHSCORE_FILE)

    def _load_best_score(self) -> int:
        try:
            path = self._get_save_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return int(data.get("best_score", 0))
        except Exception:
            pass
        return 0

    def _save_best_score(self) -> None:
        try:
            path = self._get_save_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"best_score": self._best_score}, f)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Legacy score-based difficulty methods (kept for reference but no longer
    # used during gameplay — WaveManager provides live spawn parameters).
    # ------------------------------------------------------------------

    def _current_fall_speed(self) -> float:  # pragma: no cover
        speed = S.INITIAL_FALL_SPEED + self._score * S.SPEED_SCALE_FACTOR
        return min(speed, S.MAX_FALL_SPEED)

    def _current_spawn_interval(self) -> float:  # pragma: no cover
        interval = S.INITIAL_SPAWN_INTERVAL - self._score * S.SPAWN_SCALE_FACTOR
        return max(interval, S.MIN_SPAWN_INTERVAL)
