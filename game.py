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
import math
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
# Stability tracker — tracks continuous gesture hold per hand
# ---------------------------------------------------------------------------

@dataclass
class _StabilityState:
    last_gesture: str | None = None
    hold_time: float = 0.0

    def update(self, new_gesture: str | None, dt: float) -> bool:
        """
        Returns True when the gesture has been held continuously for STABILITY_DURATION.
        Resets timer immediately if gesture changes or is None.
        """
        if new_gesture != self.last_gesture:
            self.last_gesture = new_gesture
            self.hold_time = 0.0
            return False
        if new_gesture is None:
            self.hold_time = 0.0
            return False
        self.hold_time += dt
        return self.hold_time >= S.STABILITY_DURATION


# ---------------------------------------------------------------------------
# TargetPair: Represents an active dual-hand gesture requirement
# ---------------------------------------------------------------------------

class TargetPair:
    """
    Dual-hand gameplay pair consisting of:
      - left_target: FallingTarget required for user's LEFT hand
      - right_target: FallingTarget required for user's RIGHT hand
      - Synchronization window tracking
    """

    def __init__(
        self,
        left_gesture: str,
        right_gesture: str,
        fall_speed: float,
        start_y: float = -S.TARGET_SIZE // 2,
        shm_phase: float = 0.0,
    ) -> None:
        # Opposing phases create a dynamic mirrored dance effect: when left moves outward, right moves outward
        self.left_target = FallingTarget(
            gesture_name=left_gesture,
            lane=0,
            x=float(S.LEFT_TARGET_X),
            start_y=start_y,
            fall_speed=fall_speed,
            hand_side="LEFT",
            shm_phase=shm_phase,
        )
        self.right_target = FallingTarget(
            gesture_name=right_gesture,
            lane=1,
            x=float(S.RIGHT_TARGET_X),
            start_y=start_y,
            fall_speed=fall_speed,
            hand_side="RIGHT",
            shm_phase=shm_phase + math.pi,  # pi phase shift creates mirrored/opposing harmonic oscillation
        )

        # Per-side match timestamp (monotonic time when side was validated)
        self.left_matched_time: float | None = None
        self.right_matched_time: float | None = None

        self.is_completed: bool = False
        self.is_missed: bool = False

    @property
    def is_alive(self) -> bool:
        return self.left_target.is_alive and self.right_target.is_alive and not self.is_completed

    @property
    def is_done(self) -> bool:
        return self.left_target.is_done and self.right_target.is_done

    @property
    def y(self) -> float:
        return self.left_target.y

    def update(self, dt: float) -> None:
        """Update both targets and expire single-side match if sync window elapsed."""
        now = time.monotonic()

        # Check sync window expiration for single-hand matches
        if not self.is_completed:
            if self.left_matched_time is not None and self.right_matched_time is None:
                if now - self.left_matched_time > S.SYNC_WINDOW_SEC:
                    # Sync window expired! Reset left match so player can try again
                    self.left_matched_time = None
                    self.left_target.is_matched = False

            elif self.right_matched_time is not None and self.left_matched_time is None:
                if now - self.right_matched_time > S.SYNC_WINDOW_SEC:
                    # Sync window expired! Reset right match so player can try again
                    self.right_matched_time = None
                    self.right_target.is_matched = False

        self.left_target.update(dt)
        self.right_target.update(dt)

        # If either target crossed danger line, whole pair is missed
        if (self.left_target.state == TargetState.MISSED or self.right_target.state == TargetState.MISSED) and not self.is_missed:
            self.miss()

    def draw(self, surface: "pygame.Surface") -> None:
        self.left_target.draw(surface)
        self.right_target.draw(surface)

    def mark_left_matched(self, now: float) -> None:
        self.left_matched_time = now
        self.left_target.is_matched = True

    def mark_right_matched(self, now: float) -> None:
        self.right_matched_time = now
        self.right_target.is_matched = True

    def destroy_both(self) -> None:
        self.is_completed = True
        self.left_target.destroy()
        self.right_target.destroy()

    def miss(self) -> None:
        self.is_missed = True
        self.left_target.miss()
        self.right_target.miss()


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    """
    Central game state for HandSign Rush 2.0 (Dual-Hand Gesture Sync).
    Call reset() before each new game, update() each frame.
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

        # Active target pairs (dual-hand pairs)
        self._active_pairs: list[TargetPair] = []
        self._spawn_timer: float = 0.0
        self._last_pair_clear_time: float = 0.0

        # Independent stability trackers for Left and Right hands
        self._left_stability = _StabilityState()
        self._right_stability = _StabilityState()

        # Events that main.py reads each frame
        self.life_lost_this_frame: bool = False
        self.target_destroyed_this_frame: bool = False
        self.perfect_sync_this_frame: bool = False

    def reset(self) -> None:
        """Prepare for a fresh game run."""
        self.wave_manager.reset()
        self._lives = S.INITIAL_LIVES
        self._score = 0
        self._combo = 0
        self._active_pairs = []
        self._spawn_timer = 0.0
        self._last_pair_clear_time = 0.0
        self._left_stability = _StabilityState()
        self._right_stability = _StabilityState()
        self.life_lost_this_frame = False
        self.target_destroyed_this_frame = False
        self.perfect_sync_this_frame = False

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
        """Flattens active pairs into target list for legacy rendering or checks."""
        targets: list[FallingTarget] = []
        for pair in self._active_pairs:
            targets.append(pair.left_target)
            targets.append(pair.right_target)
        return targets

    @property
    def active_pairs(self) -> list[TargetPair]:
        return self._active_pairs

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
        self.perfect_sync_this_frame = False

        # 0. Tick wave manager
        self.wave_manager.update(dt)

        # 1. Read dual-hand gesture snapshot
        frame: GestureFrame = self._shared.read()
        camera_ok: bool = frame.camera_ok

        # 2. Update independent stability states for left and right hands
        left_stable = self._left_stability.update(frame.left_hand.gesture, dt)
        right_stable = self._right_stability.update(frame.right_hand.gesture, dt)

        # 3. Dual-Hand Gesture Matching
        if self.wave_manager.is_active and camera_ok:
            self._check_dual_gesture_matches(
                frame.left_hand.gesture if left_stable else None,
                frame.left_hand.confidence,
                frame.right_hand.gesture if right_stable else None,
                frame.right_hand.confidence,
            )

        # 4. Update all active pairs
        newly_missed = []
        still_active: list[TargetPair] = []
        for pair in self._active_pairs:
            pair.update(dt)
            if pair.is_missed and pair not in newly_missed:
                newly_missed.append(pair)
            if not pair.is_done:
                still_active.append(pair)

        # Process misses (one missed pair = lose 1 life, reset combo)
        for _ in newly_missed:
            self._lives = max(0, self._lives - 1)
            self._combo = 0
            self.life_lost_this_frame = True
            self.wave_manager.record_miss(camera_ok=camera_ok)
            audio_manager.play_sfx("life_lost")
            if self._lives == 1:
                audio_manager.play_sfx("low_health")

        self._active_pairs = still_active

        # Danger warning sound if any active target is close to danger line
        for pair in self._active_pairs:
            if pair.is_alive and (pair.y + S.TARGET_SIZE // 2 > S.WINDOW_H * S.DANGER_Y_FRACTION - 75):
                audio_manager.play_sfx("danger_warning")
                break

        # 5. Spawn timer for dual-hand pairs
        if self.wave_manager.spawning_allowed:
            self._spawn_timer += dt
            self._try_spawn_pair()

    def draw(self, surface: "pygame.Surface") -> None:
        """Draw all active dual target pairs."""
        for pair in self._active_pairs:
            pair.draw(surface)

    # ------------------------------------------------------------------
    # Dual-hand Spawning
    # ------------------------------------------------------------------

    def _try_spawn_pair(self) -> None:
        """
        Spawn a synchronized Left-Right target pair.
        Avoids instantly overlapping pairs: caps at wave_manager.max_targets // 2 (at least 1).
        """
        wm = self.wave_manager
        # Each pair contains 2 targets
        max_pairs = max(1, wm.max_targets // 2)

        if self._spawn_timer < wm.spawn_interval:
            return
        if len(self._active_pairs) >= max_pairs:
            self._spawn_timer = 0.0
            return

        self._spawn_timer = 0.0

        # Choose distinct gestures for left and right targets
        left_gesture = wm.next_gesture()
        right_gesture = wm.next_gesture(exclude={left_gesture})

        # Randomize initial phase so different wave pairs oscillate uniquely
        random_phase = random.uniform(0.0, math.pi * 2)

        pair = TargetPair(
            left_gesture=left_gesture,
            right_gesture=right_gesture,
            fall_speed=wm.fall_speed,
            start_y=float(-S.TARGET_SIZE // 2),
            shm_phase=random_phase,
        )
        self._active_pairs.append(pair)
        audio_manager.play_sfx("target_spawn")

    # ------------------------------------------------------------------
    # Dual-Hand Sync Matching Logic
    # ------------------------------------------------------------------

    def _check_dual_gesture_matches(
        self,
        left_gesture: str | None,
        left_conf: float,
        right_gesture: str | None,
        right_conf: float,
    ) -> None:
        """
        Validates both hands independently against active pairs:
          - Target closest to danger line (highest y) has priority.
          - Left target ONLY accepts user's left hand.
          - Right target ONLY accepts user's right hand.
          - Pair is only destroyed when both sides match within SYNC_WINDOW_SEC.
        """
        now = time.monotonic()

        # Cooldown after completing a pair prevents accidental immediate clearing
        if now - self._last_pair_clear_time < S.PAIR_COOLDOWN:
            return

        alive_pairs = [p for p in self._active_pairs if p.is_alive]
        if not alive_pairs:
            return

        # Prioritize pair closest to danger line (highest y)
        pair = max(alive_pairs, key=lambda p: p.y)

        # 1. Evaluate Left Hand against pair's left target
        if (
            left_gesture is not None
            and left_conf >= S.CONFIDENCE_THRESHOLD
            and left_gesture == pair.left_target.gesture_name
            and pair.left_matched_time is None
        ):
            pair.mark_left_matched(now)
            audio_manager.play_sfx("gesture_detected")

        # 2. Evaluate Right Hand against pair's right target
        if (
            right_gesture is not None
            and right_conf >= S.CONFIDENCE_THRESHOLD
            and right_gesture == pair.right_target.gesture_name
            and pair.right_matched_time is None
        ):
            pair.mark_right_matched(now)
            audio_manager.play_sfx("gesture_detected")

        # 3. Check Dual Synchronization Completion
        if pair.left_matched_time is not None and pair.right_matched_time is not None:
            sync_diff = abs(pair.left_matched_time - pair.right_matched_time)

            if sync_diff <= S.SYNC_WINDOW_SEC:
                # Successfully synchronized! Complete the pair!
                is_perfect_sync = sync_diff <= S.PERFECT_SYNC_WINDOW_SEC
                self._complete_pair(pair, is_perfect_sync, now)
            else:
                # Outside sync window: reset the earlier side
                if pair.left_matched_time < pair.right_matched_time:
                    pair.left_matched_time = None
                    pair.left_target.is_matched = False
                else:
                    pair.right_matched_time = None
                    pair.right_target.is_matched = False

    def _complete_pair(self, pair: TargetPair, is_perfect_sync: bool, now: float) -> None:
        """Award points, trigger SFX, and animate cancellation of both targets."""
        pair.destroy_both()
        self._last_pair_clear_time = now
        self.target_destroyed_this_frame = True
        self.perfect_sync_this_frame = is_perfect_sync

        audio_manager.play_sfx("target_hit")

        # Record hit in wave manager
        self.wave_manager.record_hit()

        # Score calculations:
        # Base points for pair + wave level multiplier
        base_pts = S.POINTS_PER_TARGET * 2 + (self.wave_manager.wave_number - 1) * 4
        bonus = int(base_pts * self._combo * S.COMBO_MULTIPLIER)
        sync_bonus = S.PERFECT_SYNC_BONUS if is_perfect_sync else 0

        old_score = self._score
        self._score += base_pts + bonus + sync_bonus
        self._combo += 1

        if is_perfect_sync:
            audio_manager.play_sfx("level_up")
        elif self._combo >= 2:
            audio_manager.play_sfx("combo")

        if (self._score // 100) > (old_score // 100):
            audio_manager.play_sfx("level_up")

        # Update and save best score
        if self._score > self._best_score:
            self._best_score = self._score
            self._save_best_score()

        # Reset stability to require fresh gestures for the next pair
        self._left_stability = _StabilityState()
        self._right_stability = _StabilityState()

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
