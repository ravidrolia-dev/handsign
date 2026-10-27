"""
target.py — FallingTarget: a falling hand-sign tile drawn entirely with Pygame
primitives (no external image assets required).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame

import settings as S

# ---------------------------------------------------------------------------
# Gesture icon renderer — all drawn with pygame.draw primitives
# ---------------------------------------------------------------------------

# Cache: gesture_name → pygame.Surface  (rendered once, reused)
_ICON_CACHE: dict[str, pygame.Surface] = {}


_EMOJI_FONT: pygame.font.Font | None = None
_EMOJI_FONT_FAILED = False


def _get_emoji_font(size: int) -> pygame.font.Font | None:
    """Load Segoe UI Emoji or system emoji font."""
    import os
    global _EMOJI_FONT_FAILED
    if _EMOJI_FONT_FAILED:
        return None

    # Try Windows Segoe UI Emoji font file directly first (fastest)
    font_path = r"C:\Windows\Fonts\seguiemj.ttf"
    if os.path.exists(font_path):
        try:
            return pygame.font.Font(font_path, size)
        except Exception:
            pass

    # Try SysFont
    try:
        return pygame.font.SysFont("segoeuiemoji", size)
    except Exception:
        _EMOJI_FONT_FAILED = True
        return None


def _make_icon(gesture: str, size: int, color: tuple[int, int, int]) -> pygame.Surface:
    """Draw a vibrant hand sign icon using emojis with fallback to geometry."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))

    # 1. Try rendering official high-definition emoji
    emoji_char = S.GESTURE_EMOJIS.get(gesture)
    if emoji_char:
        font_size = int(size * 0.72)
        font = _get_emoji_font(font_size)
        if font is not None:
            try:
                rendered = font.render(emoji_char, True, (255, 255, 255))
                # Check that glyph actually rendered pixels
                if rendered.get_width() > 0 and rendered.get_height() > 0:
                    rw, rh = rendered.get_size()
                    surf.blit(rendered, (size // 2 - rw // 2, size // 2 - rh // 2))
                    return surf
            except Exception:
                pass

    # 2. Vector procedural fallback
    cx, cy = size // 2, size // 2
    r = size // 2 - 6

    if gesture == "open_palm":
        pygame.draw.circle(surf, color, (cx, cy + 8), r // 3, 3)
        angles = [-90, -50, -15, 20, 55]
        for a in angles:
            rad = math.radians(a)
            ex = int(cx + math.cos(rad) * r)
            ey = int(cy + math.sin(rad) * r)
            sx = int(cx + math.cos(rad) * r // 3)
            sy = int(cy + math.sin(rad) * r // 3)
            pygame.draw.line(surf, color, (sx, sy + 8), (ex, ey + 8), 4)

    elif gesture == "closed_fist":
        rect = pygame.Rect(cx - r // 2, cy - r // 2 + 4, r, r)
        pygame.draw.rect(surf, color, rect, border_radius=8)
        pygame.draw.rect(surf, color, rect, 3, border_radius=8)
        for i in range(4):
            x = rect.left + (i + 1) * rect.width // 4
            pygame.draw.line(surf, _darken(color), (x, rect.top), (x, rect.top + 5), 2)

    elif gesture == "thumbs_up":
        body = pygame.Rect(cx - r // 2 + 6, cy - r // 4 + 4, r - 6, r // 2 + 4)
        pygame.draw.rect(surf, color, body, border_radius=6)
        thumb_x = body.left - 10
        thumb_top = cy - r + 2
        pygame.draw.line(surf, color, (thumb_x + 5, body.top), (thumb_x + 5, thumb_top), 6)
        pygame.draw.circle(surf, color, (thumb_x + 5, thumb_top), 5)

    elif gesture == "thumbs_down":
        body = pygame.Rect(cx - r // 2 + 6, cy - r // 4 - 4, r - 6, r // 2 + 4)
        pygame.draw.rect(surf, color, body, border_radius=6)
        thumb_x = body.left - 10
        thumb_bot = cy + r - 2
        pygame.draw.line(surf, color, (thumb_x + 5, body.bottom), (thumb_x + 5, thumb_bot), 6)
        pygame.draw.circle(surf, color, (thumb_x + 5, thumb_bot), 5)

    elif gesture == "peace_sign":
        pygame.draw.circle(surf, color, (cx, cy + 10), r // 3, 3)
        angles = [-70, -30]
        for a in angles:
            rad = math.radians(a)
            ex = int(cx + math.cos(rad) * r)
            ey = int(cy + math.sin(rad) * r)
            sx = int(cx + math.cos(rad) * r // 3)
            sy = int(cy + math.sin(rad) * r // 3)
            pygame.draw.line(surf, color, (sx, sy + 10), (ex, ey + 6), 5)

    elif gesture == "index_up":
        pygame.draw.circle(surf, color, (cx, cy + 8), r // 3, 3)
        pygame.draw.line(surf, color, (cx, cy + 8 - r // 3), (cx, cy + 8 - r + 2), 6)
        pygame.draw.circle(surf, color, (cx, cy + 8 - r + 2), 5)

    else:
        pygame.draw.circle(surf, color, (cx, cy), r, 3)
        font = pygame.font.SysFont("Arial", size // 2, bold=True)
        txt = font.render("?", True, color)
        surf.blit(txt, (cx - txt.get_width() // 2, cy - txt.get_height() // 2))

    return surf


def _darken(color: tuple[int, int, int], factor: float = 0.6) -> tuple[int, int, int]:
    return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))


def get_icon(gesture: str, size: int) -> pygame.Surface:
    """Return cached icon surface, creating it if necessary."""
    key = f"{gesture}_{size}"
    if key not in _ICON_CACHE:
        color = S.GESTURE_COLORS.get(gesture, S.NEON_CYAN)
        _ICON_CACHE[key] = _make_icon(gesture, size, color)
    return _ICON_CACHE[key]


# ---------------------------------------------------------------------------
# Particle (used by FallingTarget on destroy)
# ---------------------------------------------------------------------------

@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    color: tuple[int, int, int]
    lifetime: float
    max_lifetime: float
    radius: float

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 60 * dt  # slight gravity
        self.lifetime -= dt

    @property
    def alive(self) -> bool:
        return self.lifetime > 0

    def draw(self, surface: pygame.Surface) -> None:
        ratio = max(0.0, self.lifetime / self.max_lifetime)
        alpha = int(255 * ratio)
        sz = max(2, int(self.radius * ratio * 2))
        if sz <= 0 or alpha <= 0:
            return
        tmp = pygame.Surface((sz, sz), pygame.SRCALPHA)
        # 16-bit square pixel block
        pygame.draw.rect(tmp, (*self.color, alpha), (0, 0, sz, sz))
        # Bright core
        if sz >= 4:
            pygame.draw.rect(tmp, (255, 255, 255, min(255, alpha + 40)), (1, 1, sz - 2, sz - 2))
        surface.blit(tmp, (int(self.x) - sz // 2, int(self.y) - sz // 2))


# ---------------------------------------------------------------------------
# FallingTarget states
# ---------------------------------------------------------------------------

class TargetState(Enum):
    FALLING = auto()
    DESTROYED = auto()
    MISSED = auto()
    DONE = auto()  # animation finished, safe to remove


# ---------------------------------------------------------------------------
# FallingTarget
# ---------------------------------------------------------------------------

ANIM_DURATION = 0.45  # seconds for destroy/miss animation


class FallingTarget:
    """
    A single falling tile showing a gesture icon and label.

    Drawn entirely with Pygame primitives — no external files.
    """

    _label_font: pygame.font.Font | None = None
    _small_font: pygame.font.Font | None = None

    def __init__(
        self,
        gesture_name: str,
        lane: int,
        x: float,
        start_y: float,
        fall_speed: float,
        hand_side: str = "LEFT",  # "LEFT" or "RIGHT"
        shm_amplitude: float = S.TARGET_SHM_AMPLITUDE,
        shm_omega: float = S.TARGET_SHM_OMEGA,
        shm_phase: float = 0.0,
    ) -> None:
        self.gesture_name = gesture_name
        self.lane = lane
        self.base_x = float(x)
        self.x = float(x)
        self.y = start_y
        self.fall_speed = fall_speed
        self.hand_side = hand_side.upper()

        # Horizontal Simple Harmonic Motion (SHM) parameters: x(t) = base_x + A * sin(omega * t + phi)
        self.shm_amplitude = shm_amplitude
        self.shm_omega = shm_omega
        self.shm_phase = shm_phase
        self._elapsed_time: float = 0.0

        self.state = TargetState.FALLING
        self._anim_timer: float = 0.0

        # Ready/Matched state for dual-hand sync window
        self.is_matched: bool = False

        # Particles spawned on destroy
        self.particles: list[Particle] = []

        # Glow pulse phase
        self._pulse = random.uniform(0, math.pi * 2)

        # Cache label surface
        self._label_surf: pygame.Surface | None = None

        self._size = S.TARGET_SIZE
        self._danger_y = S.WINDOW_H * S.DANGER_Y_FRACTION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if self.state == TargetState.FALLING:
            self.y += self.fall_speed * dt
            self._elapsed_time += dt
            self._pulse += dt * 3.0

            # Horizontal Simple Harmonic Motion: x(t) = base_x + A * sin(omega * t + phase)
            # Damps slightly if target has already been matched
            amp = self.shm_amplitude * 0.4 if self.is_matched else self.shm_amplitude
            self.x = self.base_x + amp * math.sin(self.shm_omega * self._elapsed_time + self.shm_phase)

            # Check danger line
            if self.y + self._size // 2 >= self._danger_y:
                self.miss()
        elif self.state in (TargetState.DESTROYED, TargetState.MISSED):
            self._anim_timer += dt
            if self._anim_timer >= ANIM_DURATION:
                self.state = TargetState.DONE
        # Update particles regardless
        self.particles = [p for p in self.particles if p.alive]
        for p in self.particles:
            p.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        if self.state == TargetState.DONE and not self.particles:
            return

        if self.state == TargetState.FALLING:
            self._draw_falling(surface)
        elif self.state == TargetState.DESTROYED:
            self._draw_destroy_anim(surface)
        elif self.state == TargetState.MISSED:
            self._draw_miss_anim(surface)

        # Always draw particles (linger after done state for one frame)
        for p in self.particles:
            p.draw(surface)

    def destroy(self) -> None:
        """Trigger success animation and spawn particles."""
        if self.state != TargetState.FALLING:
            return
        self.state = TargetState.DESTROYED
        self._anim_timer = 0.0
        self._spawn_particles()

    def miss(self) -> None:
        """Mark as missed (crossed danger line)."""
        if self.state != TargetState.FALLING:
            return
        self.state = TargetState.MISSED
        self._anim_timer = 0.0

    @property
    def is_alive(self) -> bool:
        return self.state == TargetState.FALLING

    @property
    def is_done(self) -> bool:
        return self.state == TargetState.DONE and not self.particles

    def get_rect(self) -> pygame.Rect:
        half = self._size // 2
        return pygame.Rect(int(self.x) - half, int(self.y) - half, self._size, self._size)

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_falling(self, surface: pygame.Surface) -> None:
        half = self._size // 2
        cx, cy = int(self.x), int(self.y)
        color = S.GESTURE_COLORS.get(self.gesture_name, S.NEON_CYAN)

        # Danger proximity check (pulses red when close to danger line)
        dist_to_danger = self._danger_y - (self.y + half)
        in_danger = dist_to_danger < 85.0
        # Check if this side is in matched/ready state (awaiting other hand in sync window)
        is_ready = self.is_matched
        side_color = S.NEON_CYAN if self.hand_side == "LEFT" else S.NEON_PINK
        accent_color = S.NEON_GREEN if is_ready else color
        if in_danger and int(self._pulse * 4) % 2 == 0 and not is_ready:
            draw_color = S.DANGER_COLOR
        else:
            draw_color = accent_color

        # 1. Upward speed streaks / light trails (retro arcade falling effect)
        streak_surf = pygame.Surface((self._size + 16, 60), pygame.SRCALPHA)
        streak_offsets = [-half + 12, -half // 2, 0, half // 2, half - 12]
        for idx, ox in enumerate(streak_offsets):
            streak_len = int(24 + 18 * math.sin(self._pulse + idx * 1.2))
            st_alpha = int(90 + 50 * math.sin(self._pulse * 2 + idx))
            sx = (self._size + 16) // 2 + ox
            # Vertical gradient line fading upwards
            for sy_step in range(streak_len):
                fade = (1.0 - sy_step / streak_len)
                alpha_step = int(st_alpha * fade)
                col = (*draw_color, alpha_step)
                pygame.draw.line(streak_surf, col, (sx, 60 - sy_step), (sx, 60 - sy_step), 2)
        surface.blit(streak_surf, (cx - (self._size + 16) // 2, cy - half - 58))

        # 2. Outer rounded-square glowing aura (intense green pulse if matched!)
        glow_pad = 12 if is_ready else 8
        glow_rect = pygame.Rect(cx - half - glow_pad, cy - half - glow_pad, self._size + glow_pad * 2, self._size + glow_pad * 2)
        glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        glow_a = int(80 + 40 * math.sin(self._pulse * 3)) if is_ready else int(35 + 20 * math.sin(self._pulse))
        pygame.draw.rect(glow_surf, (*draw_color, glow_a), glow_surf.get_rect(), border_radius=16)
        pygame.draw.rect(glow_surf, (*draw_color, min(255, glow_a + 35)), glow_surf.get_rect().inflate(-4, -4), border_radius=14)
        surface.blit(glow_surf, glow_rect.topleft)

        # 3. Background tile (deep navy with pixel-styled rounded border)
        tile_rect = pygame.Rect(cx - half, cy - half, self._size, self._size)
        tile_surf = pygame.Surface((self._size, self._size), pygame.SRCALPHA)
        # Deep translucent fill
        pygame.draw.rect(tile_surf, (16, 12, 34, 230), tile_surf.get_rect(), border_radius=12)
        # Inner subtle gradient / border
        pygame.draw.rect(tile_surf, (*draw_color, 80 if is_ready else 70), tile_surf.get_rect().inflate(-4, -4), border_radius=10)
        # Outer neon border (3px)
        border_w = 4 if is_ready else 3
        pygame.draw.rect(tile_surf, (*draw_color, 255), tile_surf.get_rect(), border_w, border_radius=12)
        # Corner accent notches
        c_acc = (255, 255, 255, 230 if is_ready else 180)
        pygame.draw.line(tile_surf, c_acc, (3, 6), (6, 3), 2)
        pygame.draw.line(tile_surf, c_acc, (self._size - 4, 6), (self._size - 7, 3), 2)
        surface.blit(tile_surf, tile_rect.topleft)

        # 4. Gesture icon (centred in tile)
        icon = get_icon(self.gesture_name, self._size - 22)
        surface.blit(icon, (cx - icon.get_width() // 2, cy - half + 8))

        # 5. Label below icon
        label_surf = self._get_label()
        surface.blit(label_surf, (cx - label_surf.get_width() // 2, cy + half - label_surf.get_height() - 4))

        # 6. Hand side badge top pill ("L HAND" or "R HAND" / "✓ READY")
        badge_font = self._get_label_font()
        if is_ready:
            b_txt_str = "✓ READY"
            b_bg_col = (10, 50, 20, 230)
            b_bd_col = S.NEON_GREEN
        else:
            b_txt_str = f"{self.hand_side} HAND"
            b_bg_col = (14, 10, 32, 230)
            b_bd_col = side_color

        b_surf_txt = badge_font.render(b_txt_str, True, b_bd_col)
        bw, bh = b_surf_txt.get_width() + 14, b_surf_txt.get_height() + 6
        b_pill = pygame.Surface((bw, bh), pygame.SRCALPHA)
        pygame.draw.rect(b_pill, b_bg_col, (0, 0, bw, bh), border_radius=6)
        pygame.draw.rect(b_pill, b_bd_col, (0, 0, bw, bh), 1, border_radius=6)
        b_pill.blit(b_surf_txt, (7, 3))
        surface.blit(b_pill, (cx - bw // 2, cy - half - bh + 2))

    def _draw_destroy_anim(self, surface: pygame.Surface) -> None:
        progress = self._anim_timer / ANIM_DURATION  # 0 → 1
        color = S.GESTURE_COLORS.get(self.gesture_name, S.NEON_CYAN)
        cx, cy = int(self.x), int(self.y)

        # Expanding shockwave ring
        ring_r = int((S.TARGET_SIZE // 2 + 50) * progress)
        alpha = int(255 * (1.0 - progress))
        if ring_r > 0:
            _draw_glow_circle(surface, cx, cy, ring_r, color, alpha // 3)
            ring_surf = pygame.Surface((ring_r * 2 + 6, ring_r * 2 + 6), pygame.SRCALPHA)
            pygame.draw.circle(ring_surf, (*color, alpha), (ring_r + 3, ring_r + 3), ring_r, 4)
            surface.blit(ring_surf, (cx - ring_r - 3, cy - ring_r - 3))

        # Floating score popup text ("+10")
        score_font = self._get_small_font()
        rise_y = cy - int(progress * 40)
        pop_txt = score_font.render("+10", True, S.NEON_GREEN)
        pop_txt.set_alpha(alpha)
        surface.blit(pop_txt, (cx - pop_txt.get_width() // 2, rise_y - pop_txt.get_height() // 2))

    def _draw_miss_anim(self, surface: pygame.Surface) -> None:
        progress = self._anim_timer / ANIM_DURATION
        alpha = int(255 * (1.0 - progress))
        cx, cy = int(self.x), int(self.y)
        half = self._size // 2

        # Red flash fade-out
        tile_rect = pygame.Rect(cx - half, cy - half, self._size, self._size)
        flash = pygame.Surface((self._size, self._size), pygame.SRCALPHA)
        pygame.draw.rect(flash, (*S.DANGER_COLOR, alpha // 2), flash.get_rect(), border_radius=12)
        pygame.draw.rect(flash, (*S.DANGER_COLOR, alpha), flash.get_rect(), 3, border_radius=12)
        surface.blit(flash, tile_rect.topleft)

        # "✗" symbol
        if progress < 0.6:
            font = self._get_small_font()
            cross = font.render("✗", True, S.DANGER_COLOR)
            cross.set_alpha(alpha)
            surface.blit(cross, (cx - cross.get_width() // 2, cy - cross.get_height() // 2))

    # ------------------------------------------------------------------
    # Font helpers (lazy init to avoid calls before pygame.init)
    # ------------------------------------------------------------------

    def _get_label(self) -> pygame.Surface:
        if self._label_surf is None:
            font = self._get_label_font()
            label_text = S.GESTURE_LABELS.get(self.gesture_name, self.gesture_name).upper()
            color = S.GESTURE_COLORS.get(self.gesture_name, S.NEON_CYAN)
            txt = font.render(label_text, True, color)
            sh = font.render(label_text, True, (10, 8, 20))
            w, h = txt.get_size()
            surf = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
            surf.blit(sh, (2, 2))
            surf.blit(txt, (1, 1))
            self._label_surf = surf
        return self._label_surf

    @classmethod
    def _get_label_font(cls) -> pygame.font.Font:
        if cls._label_font is None:
            import os
            font_path = os.path.join(os.path.dirname(__file__), "assets", "PressStart2P-Regular.ttf")
            if os.path.exists(font_path):
                try:
                    cls._label_font = pygame.font.Font(font_path, 8)
                    return cls._label_font
                except Exception:
                    pass
            cls._label_font = pygame.font.SysFont("Arial", 12, bold=True)
        return cls._label_font

    @classmethod
    def _get_small_font(cls) -> pygame.font.Font:
        if cls._small_font is None:
            cls._small_font = pygame.font.SysFont("Arial", 36, bold=True)
        return cls._small_font

    # ------------------------------------------------------------------
    # Particle helpers
    # ------------------------------------------------------------------

    def _spawn_particles(self) -> None:
        color = S.GESTURE_COLORS.get(self.gesture_name, S.NEON_CYAN)
        for _ in range(S.PARTICLE_COUNT_PER_DESTROY):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(S.PARTICLE_SPEED * 0.5, S.PARTICLE_SPEED * 1.5)
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed
            lt = random.uniform(S.PARTICLE_LIFETIME * 0.5, S.PARTICLE_LIFETIME)
            r = random.uniform(3, 7)
            self.particles.append(
                Particle(self.x, self.y, vx, vy, color, lt, lt, r)
            )


# ---------------------------------------------------------------------------
# Helper: draw a soft glow circle using a transparent surface
# ---------------------------------------------------------------------------

def _draw_glow_circle(
    surface: pygame.Surface,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
    alpha: int,
) -> None:
    if radius <= 0 or alpha <= 0:
        return
    d = radius * 2 + 4
    glow = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(glow, (*color, max(0, min(255, alpha))), (radius + 2, radius + 2), radius)
    surface.blit(glow, (cx - radius - 2, cy - radius - 2))
