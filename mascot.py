"""
mascot.py — HandSign Rush Mascot Animation System.

Handles frame-based 16-bit pixel-art sprite animation with independent time-based
updating, stable torso centering, baseline anchoring, nearest-neighbor scaling,
and state machine transitions (IDLE, RUN, JUMP, HURT, VICTORY).
"""

from __future__ import annotations

import math
import os
from enum import Enum
from typing import Dict, List, Optional, Tuple
import pygame


class MascotState(Enum):
    IDLE = "idle"
    RUN = "run"
    JUMP = "jump"
    HURT = "hurt"
    VICTORY = "victory"


# Tuned animation frame rates (frames per second) for natural retro cadence
DEFAULT_FPS: Dict[MascotState, float] = {
    MascotState.IDLE: 6.0,      # Gentle, natural breathing and ribbon wave
    MascotState.RUN: 11.0,      # Rhythmic, crisp 8-frame running cadence
    MascotState.JUMP: 8.0,      # Airborne arc with clean crouch, apex, and landing
    MascotState.HURT: 6.5,      # High-visibility recoil stagger
    MascotState.VICTORY: 8.0,   # Celebratory cheer and victory stance
}

FRAME_COUNTS: Dict[MascotState, int] = {
    MascotState.IDLE: 6,
    MascotState.RUN: 8,
    MascotState.JUMP: 6,
    MascotState.HURT: 4,
    MascotState.VICTORY: 6,
}

# The reference foot baseline in the master 128x128 canvas
CANVAS_DIM: int = 128
FOOT_BASELINE_Y: int = 118


class Mascot:
    """
    Animated character mascot controller for HandSign Rush.
    Preserves 16-bit pixel-art aesthetics, stable body anchoring,
    and responsive state-machine reactions.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        target_size: Tuple[int, int] = (112, 112),
        initial_state: MascotState = MascotState.IDLE,
    ):
        """
        Initialize mascot with time-based animation and scaled caches.

        Args:
            base_dir: Directory containing idle/, run/, jump/, hurt/, victory/.
            target_size: (width, height) in pixels. 112x112 produces a ~96px tall character,
                         matching 100-130px at 1600x900 resolution proportionally.
            initial_state: Starting MascotState.
        """
        if base_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.join(script_dir, "assets", "character", "mascot")

        self.base_dir = base_dir
        self.target_size = target_size
        self.state = initial_state
        self.current_frame_idx = 0
        self.anim_timer = 0.0
        self.is_looping = True
        self.is_finished = False
        self.facing_left = False

        # One-shot auto-transition target
        self.on_animation_end_state: Optional[MascotState] = None

        # Polish mechanics: landing bounce and idle flair
        self._landing_bounce_timer = 0.0
        self._landing_bounce_duration = 0.16
        self._idle_time_accum = 0.0
        self._idle_flair_interval = 5.5  # seconds before occasional playful idle hop

        # In-game movement coordinates
        self.x: float = 120.0
        self.y: float = 0.0
        self.move_speed: float = 85.0    # pixels/sec jog speed
        self.patrol_min_x: float = 75.0
        self.patrol_max_x: float = 210.0
        self.patrol_dir: float = 1.0

        # Sprite frames: raw surfaces and nearest-neighbor scaled caches
        self._raw_frames: Dict[MascotState, List[pygame.Surface]] = {}
        self._scaled_frames: Dict[MascotState, List[pygame.Surface]] = {}
        self._scaled_flipped_frames: Dict[MascotState, List[pygame.Surface]] = {}
        self._converted = False

        self._load_all_frames()

    def _load_all_frames(self) -> None:
        """Load sprite frames from disk and build pre-scaled pixel-art caches."""
        for state in MascotState:
            state_frames: List[pygame.Surface] = []
            state_dir = os.path.join(self.base_dir, state.value)
            count = FRAME_COUNTS.get(state, 6)

            for i in range(count):
                frame_file = os.path.join(state_dir, f"{state.value}_{i}.png")
                if os.path.exists(frame_file):
                    try:
                        # Load as software surface first; converted to alpha lazily
                        raw_surf = pygame.image.load(frame_file)
                        state_frames.append(raw_surf)
                    except Exception as e:
                        print(f"[Mascot] Warning: failed to load {frame_file}: {e}")

            # Fallback if frames missing
            if not state_frames:
                state_frames = [self._create_fallback_surface(state)]

            self._raw_frames[state] = state_frames

        self._rebuild_scaled_caches()

    def _rebuild_scaled_caches(self) -> None:
        """Rebuild nearest-neighbor pre-scaled frame caches."""
        self._scaled_frames = {}
        self._scaled_flipped_frames = {}

        for state, frames in self._raw_frames.items():
            scaled_list: List[pygame.Surface] = []
            flipped_list: List[pygame.Surface] = []

            for frame in frames:
                # Nearest-neighbor scale preserves crisp, sharp pixel art
                scaled = pygame.transform.scale(frame, self.target_size)
                flipped = pygame.transform.flip(scaled, True, False)
                scaled_list.append(scaled)
                flipped_list.append(flipped)

            self._scaled_frames[state] = scaled_list
            self._scaled_flipped_frames[state] = flipped_list

    def _ensure_converted(self) -> None:
        """Ensure surfaces are converted with display alpha for fast blitting."""
        if self._converted or pygame.display.get_surface() is None:
            return

        try:
            for state in MascotState:
                self._scaled_frames[state] = [
                    f.convert_alpha() for f in self._scaled_frames.get(state, [])
                ]
                self._scaled_flipped_frames[state] = [
                    f.convert_alpha() for f in self._scaled_flipped_frames.get(state, [])
                ]
            self._converted = True
        except Exception:
            pass

    def set_target_size(self, target_size: Tuple[int, int]) -> None:
        """Update display size with nearest-neighbor scaling."""
        if self.target_size != target_size:
            self.target_size = target_size
            self._rebuild_scaled_caches()
            self._converted = False

    def set_state(
        self,
        new_state: MascotState,
        loop: bool = True,
        force_restart: bool = False,
        return_to: Optional[MascotState] = None,
    ) -> None:
        """
        Transition mascot to a new animation state.
        Avoids restarting running or idle animations if already in that state.
        """
        if self.state != new_state or force_restart:
            # Check if transitioning from JUMP to grounded state for landing bounce
            if self.state == MascotState.JUMP and new_state in (MascotState.RUN, MascotState.IDLE):
                self._landing_bounce_timer = self._landing_bounce_duration

            self.state = new_state
            self.current_frame_idx = 0
            self.anim_timer = 0.0
            self.is_finished = False
            self.is_looping = loop
            self.on_animation_end_state = return_to

            if new_state == MascotState.IDLE:
                self._idle_time_accum = 0.0

    def play_action(
        self,
        action: MascotState,
        return_to: MascotState = MascotState.IDLE,
    ) -> None:
        """Play a high-priority one-shot action and return to baseline state afterwards."""
        self.set_state(action, loop=False, force_restart=True, return_to=return_to)

    def trigger_jump(self, return_to: MascotState = MascotState.IDLE) -> None:
        """Trigger one-shot jump celebration."""
        self.play_action(MascotState.JUMP, return_to=return_to)

    def trigger_victory(self, return_to: MascotState = MascotState.IDLE) -> None:
        """Trigger one-shot victory animation."""
        self.play_action(MascotState.VICTORY, return_to=return_to)

    def trigger_hurt(self, return_to: MascotState = MascotState.IDLE) -> None:
        """Trigger one-shot hurt reaction."""
        self.play_action(MascotState.HURT, return_to=return_to)

    def trigger_run(self) -> None:
        """Switch to continuous looping run animation."""
        self.set_state(MascotState.RUN, loop=True)

    def trigger_idle(self) -> None:
        """Switch to continuous looping idle animation."""
        self.set_state(MascotState.IDLE, loop=True)

    def update(self, dt: float) -> None:
        """
        Advance time-based animation independent of display frame rate.

        Args:
            dt: Delta time in seconds.
        """
        # Update landing bounce
        if self._landing_bounce_timer > 0.0:
            self._landing_bounce_timer = max(0.0, self._landing_bounce_timer - dt)

        # Update idle flair check
        if self.state == MascotState.IDLE and self.is_looping:
            self._idle_time_accum += dt
            if self._idle_time_accum >= self._idle_flair_interval:
                self._idle_time_accum = 0.0
                # Playful idle hop
                self.trigger_jump(return_to=MascotState.IDLE)
                return

        if self.is_finished:
            return

        fps = DEFAULT_FPS.get(self.state, 8.0)
        frame_duration = 1.0 / max(1.0, fps)
        self.anim_timer += dt

        frames = self._scaled_frames.get(self.state, [])
        num_frames = len(frames)
        if num_frames == 0:
            return

        while self.anim_timer >= frame_duration:
            self.anim_timer -= frame_duration
            if self.current_frame_idx + 1 < num_frames:
                self.current_frame_idx += 1
            else:
                if self.is_looping:
                    self.current_frame_idx = 0
                else:
                    self.is_finished = True
                    # Check automatic transition
                    if self.on_animation_end_state is not None:
                        target = self.on_animation_end_state
                        self.on_animation_end_state = None
                        self.set_state(target, loop=True)
                    break

    def update_gameplay_patrol(self, dt: float) -> None:
        """
        Advance running traversal along the platform during gameplay.
        Keeps mascot moving smoothly within its designated left play zone.
        """
        if self.state == MascotState.RUN:
            self.x += self.move_speed * dt * self.patrol_dir
            if self.patrol_dir > 0 and self.x >= self.patrol_max_x:
                self.x = self.patrol_max_x
                self.patrol_dir = -1.0
                self.facing_left = True
            elif self.patrol_dir < 0 and self.x <= self.patrol_min_x:
                self.x = self.patrol_min_x
                self.patrol_dir = 1.0
                self.facing_left = False

    def get_current_frame(self) -> pygame.Surface:
        """Get the current scaled Surface for rendering."""
        self._ensure_converted()
        cache = self._scaled_flipped_frames if self.facing_left else self._scaled_frames
        frames = cache.get(self.state, [])
        if not frames:
            return self._create_fallback_surface(self.state)

        idx = min(self.current_frame_idx, len(frames) - 1)
        return frames[idx]

    def draw(
        self,
        surface: pygame.Surface,
        pos: Tuple[int, int],
        anchor: str = "bottom_center",
    ) -> pygame.Rect:
        """
        Draw mascot onto surface with precise foot baseline alignment.

        Args:
            surface: Destination pygame.Surface.
            pos: (x, y). When anchor is 'bottom_center', y represents the ground platform line.
            anchor: Positioning anchor ('bottom_center', 'center', 'top_left').

        Returns:
            The blitted pygame.Rect on screen.
        """
        frame = self.get_current_frame()
        w, h = frame.get_size()
        x, y = pos

        # Foot offset: where the feet rest inside the scaled canvas
        foot_offset_in_surf = int(round(FOOT_BASELINE_Y * h / float(CANVAS_DIM)))

        # Landing bounce offset (subtle squash/rebound on touchdown)
        bounce_y = 0
        if self._landing_bounce_timer > 0.0:
            bounce_prog = 1.0 - (self._landing_bounce_timer / self._landing_bounce_duration)
            bounce_y = int(round(math.sin(bounce_prog * math.pi) * 3.5))

        if anchor == "bottom_center":
            draw_x = x - w // 2
            draw_y = (y - foot_offset_in_surf) + bounce_y
        elif anchor == "center":
            draw_x = x - w // 2
            draw_y = y - h // 2
        elif anchor == "bottom_left":
            draw_x = x
            draw_y = (y - foot_offset_in_surf) + bounce_y
        else:  # 'top_left'
            draw_x = x
            draw_y = y

        dest_rect = pygame.Rect(draw_x, draw_y, w, h)
        surface.blit(frame, dest_rect)
        return dest_rect

    def _create_fallback_surface(self, state: MascotState) -> pygame.Surface:
        """Procedural 128x128 pixel-art surface if assets are missing."""
        surf = pygame.Surface((128, 128), pygame.SRCALPHA)
        # White body
        pygame.draw.circle(surf, (245, 245, 255), (64, 60), 32)
        pygame.draw.circle(surf, (15, 23, 42), (64, 60), 32, 4)
        # Red headband
        pygame.draw.rect(surf, (220, 38, 38), (36, 44, 56, 14), border_radius=3)
        pygame.draw.rect(surf, (15, 23, 42), (36, 44, 56, 14), 2, border_radius=3)
        # Face
        pygame.draw.ellipse(surf, (15, 23, 42), (52, 60, 6, 10))
        pygame.draw.ellipse(surf, (15, 23, 42), (70, 60, 6, 10))
        # Shoes
        pygame.draw.rect(surf, (220, 38, 38), (44, 110, 18, 8), border_radius=2)
        pygame.draw.rect(surf, (220, 38, 38), (66, 110, 18, 8), border_radius=2)
        return surf
