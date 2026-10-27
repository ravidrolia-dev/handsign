"""
ui.py — All Pygame rendering: menus, HUD, webcam preview, buttons,
background, danger line, overlays, and retro 16-bit arcade visual effects.
"""

from __future__ import annotations

import math
import os
import random

import cv2
import numpy as np
import pygame

import settings as S
from hand_tracker import GestureFrame
from mascot import Mascot, MascotState


# ---------------------------------------------------------------------------
# Font helpers (loads PressStart2P or system fonts with graceful fallback)
# ---------------------------------------------------------------------------

_PIXEL_FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "PressStart2P-Regular.ttf")


def _get_pixel_font(size: int) -> pygame.font.Font:
    """Load bundled 16-bit pixel font, falling back to clean system font."""
    if os.path.exists(_PIXEL_FONT_PATH):
        try:
            return pygame.font.Font(_PIXEL_FONT_PATH, size)
        except Exception:
            pass
    for name in ["Impact", "Segoe UI Black", "Consolas", "Arial"]:
        try:
            return pygame.font.SysFont(name, size, bold=True)
        except Exception:
            continue
    return pygame.font.Font(None, size)


def _get_system_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ["Segoe UI", "Arial", "Consolas"]:
        try:
            return pygame.font.SysFont(name, size, bold=bold)
        except Exception:
            continue
    return pygame.font.Font(None, size)


def _get_emoji_font(size: int) -> pygame.font.Font:
    font_path = r"C:\Windows\Fonts\seguiemj.ttf"
    if os.path.exists(font_path):
        try:
            return pygame.font.Font(font_path, size)
        except Exception:
            pass
    try:
        return pygame.font.SysFont("segoeuiemoji", size)
    except Exception:
        return pygame.font.Font(None, size)


# ---------------------------------------------------------------------------
# Button (16-bit Retro Arcade Beveled Button)
# ---------------------------------------------------------------------------

class Button:
    """
    A 16-bit retro arcade button with 3D pixel beveled borders,
    corner notches, hover glows, and distinct arcade styles.
    """

    def __init__(
        self,
        rect: pygame.Rect,
        label: str,
        display_label: str | None = None,
        color: tuple[int, int, int] | None = None,
        font_size: int = 14,
        style: str = "auto",
    ) -> None:
        self.rect = rect
        self.label = label
        self.display_label = display_label or label
        self._custom_color = color

        # Auto-adjust font size to avoid overflow in pixel font
        if font_size == 14 and len(self.display_label) >= 12:
            self._font_size = 10 if len(self.display_label) >= 16 else 11
        else:
            self._font_size = font_size

        self._font: pygame.font.Font | None = None

        # Auto-detect style from label if requested
        if style == "auto":
            lbl = label.lower()
            if any(k in lbl for k in ["play", "continue", "resume", "play again"]):
                self.style = "yellow"
            elif any(k in lbl for k in ["how to play", "retry", "menu", "main menu"]):
                self.style = "purple"
            else:
                self.style = "navy"
        else:
            self.style = style

    def draw(self, surface: pygame.Surface, hovered: bool = False) -> None:
        r = self.rect

        # Style palette definitions
        if self.style == "yellow":
            # Golden yellow arcade button
            bg_top = (255, 215, 30) if not hovered else (255, 235, 80)
            bg_bot = (220, 160, 0) if not hovered else (240, 180, 20)
            border_hi = (255, 248, 170)
            border_sh = (150, 95, 0)
            text_col = (20, 15, 5)
            glow_col = (255, 200, 40)
        elif self.style == "purple":
            # Royal deep purple arcade button
            bg_top = (75, 42, 130) if not hovered else (100, 58, 170)
            bg_bot = (45, 24, 85) if not hovered else (65, 34, 120)
            border_hi = (180, 100, 255)
            border_sh = (30, 15, 60)
            text_col = (250, 250, 255)
            glow_col = S.NEON_VIOLET
        else:
            # Midnight navy / slate button
            bg_top = (35, 42, 80) if not hovered else (52, 62, 115)
            bg_bot = (20, 24, 52) if not hovered else (32, 38, 75)
            border_hi = (90, 120, 195)
            border_sh = (12, 16, 36)
            text_col = (220, 225, 245)
            glow_col = S.NEON_CYAN

        # Hover aura glow
        if hovered:
            glow = pygame.Surface((r.width + 16, r.height + 16), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*glow_col, 50), (0, 0, r.width + 16, r.height + 16), border_radius=8)
            surface.blit(glow, (r.x - 8, r.y - 8))

        # 3D Beveled Face with subtle vertical gradient
        btn_surf = pygame.Surface((r.width, r.height))
        for line_y in range(r.height):
            ratio = line_y / max(1, r.height - 1)
            cr = int(bg_top[0] + (bg_bot[0] - bg_top[0]) * ratio)
            cg = int(bg_top[1] + (bg_bot[1] - bg_top[1]) * ratio)
            cb = int(bg_top[2] + (bg_bot[2] - bg_top[2]) * ratio)
            pygame.draw.line(btn_surf, (cr, cg, cb), (0, line_y), (r.width, line_y))

        # 3D Pixel Bevel outlines
        # Highlight top & left (2px)
        pygame.draw.line(btn_surf, border_hi, (2, 2), (r.width - 3, 2), 2)
        pygame.draw.line(btn_surf, border_hi, (2, 2), (2, r.height - 3), 2)
        # Shadow bottom & right (2px)
        pygame.draw.line(btn_surf, border_sh, (2, r.height - 3), (r.width - 3, r.height - 3), 2)
        pygame.draw.line(btn_surf, border_sh, (r.width - 3, 2), (r.width - 3, r.height - 3), 2)
        # Outer dark frame
        pygame.draw.rect(btn_surf, (10, 8, 20), (0, 0, r.width, r.height), 2)

        # Stepped 45-degree pixel corners
        btn_surf.set_at((0, 0), (0, 0, 0, 0))
        btn_surf.set_at((1, 0), (0, 0, 0, 0))
        btn_surf.set_at((0, 1), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 1, 0), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 2, 0), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 1, 1), (0, 0, 0, 0))
        btn_surf.set_at((0, r.height - 1), (0, 0, 0, 0))
        btn_surf.set_at((1, r.height - 1), (0, 0, 0, 0))
        btn_surf.set_at((0, r.height - 2), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 1, r.height - 1), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 2, r.height - 1), (0, 0, 0, 0))
        btn_surf.set_at((r.width - 1, r.height - 2), (0, 0, 0, 0))

        surface.blit(btn_surf, r.topleft)

        # Label with shadow
        font = self._get_font()
        # Text drop shadow
        sh_col = (0, 0, 0) if self.style != "yellow" else (180, 130, 0)
        sh_txt = font.render(self.display_label, True, sh_col)
        surface.blit(sh_txt, (r.centerx - sh_txt.get_width() // 2 + 1, r.centery - sh_txt.get_height() // 2 + 1))

        txt = font.render(self.display_label, True, text_col)
        surface.blit(txt, (r.centerx - txt.get_width() // 2, r.centery - txt.get_height() // 2))

    def is_hovered(self, pos: tuple[int, int]) -> bool:
        return self.rect.collidepoint(pos)

    def _get_font(self) -> pygame.font.Font:
        if self._font is None:
            # Try pixel font first, fall back to impact/arial
            self._font = _get_pixel_font(self._font_size)
        return self._font


# ---------------------------------------------------------------------------
# UIRenderer
# ---------------------------------------------------------------------------

class UIRenderer:
    """
    Centralised 16-bit retro arcade renderer for all screens.
    Incorporates pixel-art frames, atmospheric city skyline with lit windows,
    cute running hand mascot, retro arcade headers, and high-visibility HUD.
    """

    def __init__(self, surface: pygame.Surface) -> None:
        self._surface = surface
        self._w = surface.get_width()
        self._h = surface.get_height()

        # Cached background surface
        self._bg_base: pygame.Surface | None = None
        self._stars: list[tuple[int, int, int, float]] = []

        # City background asset
        self._city_img: pygame.Surface | None = None
        self._load_city_background()

        # Webcam preview geometry
        self._prev_w = S.CAM_PREVIEW_W
        self._prev_h = S.CAM_PREVIEW_H
        self._prev_x = self._w - self._prev_w - 20
        self._prev_y = 20

        # Danger zone position
        self._danger_y = int(self._h * S.DANGER_Y_FRACTION)

        # Initialize starfield
        random.seed(42)
        for _ in range(80):
            sx = random.randint(10, self._w - 10)
            sy = random.randint(10, int(self._h * 0.58))
            sz = random.choice([1, 1, 2, 2, 3])
            speed = random.uniform(1.5, 4.0)
            self._stars.append((sx, sy, sz, speed))
        random.seed()

        # Mascot animation system (white glove hand with red headband & sneakers)
        # 112x112 target size produces ~96px tall character (equivalent to 120px at 1600x900)
        self.mascot = Mascot(target_size=(112, 112), initial_state=MascotState.IDLE)

    def _load_city_background(self) -> None:
        asset_path = os.path.join(os.path.dirname(__file__), "assets", "Neon Pixel Cyberpunk Cityscape.png")
        if os.path.exists(asset_path):
            try:
                raw = pygame.image.load(asset_path).convert()
                self._city_img = pygame.transform.smoothscale(raw, (self._w, self._h))
                # Add dark moody overlay so game elements pop with maximum contrast
                overlay = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
                overlay.fill((12, 10, 32, 160))
                self._city_img.blit(overlay, (0, 0))
            except Exception:
                self._city_img = None

    # ------------------------------------------------------------------
    # Background & Frame
    # ------------------------------------------------------------------

    def draw_background(self, tick: int = 0) -> None:
        """Render the 16-bit night sky, city skyline, stars, and stone platform."""
        # 1. Base sky gradient or city image backdrop
        if self._city_img is not None:
            self._surface.blit(self._city_img, (0, 0))
        else:
            if self._bg_base is None:
                self._bg_base = self._make_procedural_sky()
            self._surface.blit(self._bg_base, (0, 0))

        # 2. Twinkling pixel stars in the sky
        for sx, sy, sz, speed in self._stars:
            twinkle = int(140 + 115 * math.sin(tick * 0.05 * speed + sx))
            star_col = (twinkle, twinkle, min(255, twinkle + 40))
            if sz == 1:
                self._surface.set_at((sx, sy), star_col)
            elif sz == 2:
                pygame.draw.rect(self._surface, star_col, (sx, sy, 2, 2))
            else:
                # 4-pointed cross star
                pygame.draw.line(self._surface, star_col, (sx - 2, sy), (sx + 2, sy), 1)
                pygame.draw.line(self._surface, star_col, (sx, sy - 2), (sx, sy + 2), 1)

        # 3. Pixel Moon (top right)
        moon_x, moon_y = self._w - 200, 95
        pygame.draw.circle(self._surface, (160, 200, 255, 30), (moon_x, moon_y), 32)
        pygame.draw.circle(self._surface, (215, 230, 255), (moon_x, moon_y), 22)
        # Moon craters
        pygame.draw.circle(self._surface, (185, 200, 235), (moon_x - 6, moon_y - 4), 6)
        pygame.draw.circle(self._surface, (185, 200, 235), (moon_x + 8, moon_y + 6), 5)
        pygame.draw.circle(self._surface, (185, 200, 235), (moon_x + 4, moon_y - 8), 3)

        # 4. Foreground stone ledge / platform (bottom)
        platform_h = 74
        plat_y = self._h - platform_h
        plat_surf = pygame.Surface((self._w, platform_h))
        plat_surf.fill((22, 18, 44))
        # Top ledge highlight
        pygame.draw.line(plat_surf, (85, 60, 140), (0, 0), (self._w, 0), 3)
        pygame.draw.line(plat_surf, (130, 95, 200), (0, 1), (self._w, 1), 1)
        # Stone brick seams
        brick_w = 48
        for bx in range(0, self._w, brick_w):
            pygame.draw.line(plat_surf, (15, 12, 30), (bx, 3), (bx, 36), 2)
            pygame.draw.line(plat_surf, (15, 12, 30), (bx + brick_w // 2, 36), (bx + brick_w // 2, platform_h), 2)
        pygame.draw.line(plat_surf, (15, 12, 30), (0, 36), (self._w, 36), 2)

        # Pixel moss/vines on edges
        for mx in [40, 120, 260, 380, 520, 780, 940, 1100]:
            pygame.draw.rect(plat_surf, S.NEON_GREEN, (mx, 0, 8, 4))
            pygame.draw.rect(plat_surf, (40, 180, 80), (mx + 2, 4, 4, 5))

        self._surface.blit(plat_surf, (0, plat_y))

    def _make_procedural_sky(self) -> pygame.Surface:
        """Deep midnight blue sky gradient with city silhouette skyline."""
        bg = pygame.Surface((self._w, self._h))
        top = (8, 6, 24)
        bot = (26, 18, 55)
        for y in range(self._h):
            t = y / self._h
            r = int(top[0] + (bot[0] - top[0]) * t)
            g = int(top[1] + (bot[1] - top[1]) * t)
            b = int(top[2] + (bot[2] - top[2]) * t)
            pygame.draw.line(bg, (r, g, b), (0, y), (self._w, y))

        # City Skyline Silhouette layers
        random.seed(99)
        # Far silhouette (dark indigo)
        curr_x = 0
        while curr_x < self._w:
            bw = random.randint(45, 90)
            bh = random.randint(120, 260)
            by = self._h - 74 - bh
            pygame.draw.rect(bg, (18, 14, 42), (curr_x, by, bw, bh))
            # Window lights
            for wy in range(by + 16, self._h - 90, 20):
                for wx in range(curr_x + 8, curr_x + bw - 10, 14):
                    if random.random() < 0.35:
                        w_col = random.choice([(255, 220, 100), (0, 240, 255), (160, 100, 240)])
                        pygame.draw.rect(bg, w_col, (wx, wy, 4, 6))
            curr_x += bw - random.randint(2, 8)

        random.seed()
        return bg

    def draw_retro_frame(self, badge_label: str = "") -> None:
        """Draw the authentic 16-bit arcade double-border with corner notches and top badge."""
        m = 10
        w, h = self._w - m * 2, self._h - m * 2
        rect = pygame.Rect(m, m, w, h)

        # Outer neon violet/blue border (3px)
        pygame.draw.rect(self._surface, (135, 75, 230), rect, 3, border_radius=8)
        # Inner thin accent border (1px)
        pygame.draw.rect(self._surface, (60, 35, 110), rect.inflate(-6, -6), 1, border_radius=6)

        # Stepped corner pixel brackets
        c_size = 18
        corners = [
            (rect.left, rect.top),
            (rect.right - c_size, rect.top),
            (rect.left, rect.bottom - c_size),
            (rect.right - c_size, rect.bottom - c_size),
        ]
        for cx, cy in corners:
            pygame.draw.rect(self._surface, S.NEON_CYAN, (cx, cy, c_size, 3))
            pygame.draw.rect(self._surface, S.NEON_CYAN, (cx, cy, 3, c_size))

        # Top Center Badge (e.g. "1. MAIN MENU", "2. CAMERA CHECK", "3. GAMEPLAY")
        if badge_label:
            font = _get_pixel_font(12)
            badge_txt = font.render(badge_label, True, (240, 240, 255))
            bw = badge_txt.get_width() + 32
            bh = 26
            bx = self._w // 2 - bw // 2
            by = m - 6

            # Dark pill with neon purple border
            pygame.draw.rect(self._surface, (14, 10, 32), (bx, by, bw, bh), border_radius=13)
            pygame.draw.rect(self._surface, (150, 80, 245), (bx, by, bw, bh), 2, border_radius=13)
            self._surface.blit(badge_txt, (bx + 16, by + 6))

    # ------------------------------------------------------------------
    # Mascot Animation (Animated pixel hand with red headband & sneakers)
    # ------------------------------------------------------------------

    def _draw_mascot(self, x: int = 135, y: int | None = None) -> None:
        """Draw animated retro pixel-art hand mascot along the stone ledge."""
        plat_ledge_y = self._h - 74
        draw_y = plat_ledge_y if y is None else y
        self.mascot.draw(self._surface, (x, draw_y), anchor="bottom_center")

    # ------------------------------------------------------------------
    # Floating Title Badges (around the menu title)
    # ------------------------------------------------------------------

    def _draw_floating_target_badge(
        self, gesture: str, cx: int, cy: int, tick: int, size: int = 56
    ) -> None:
        """Render a floating neon gesture badge with upward speed trails framing the title."""
        color = S.GESTURE_COLORS.get(gesture, S.NEON_CYAN)
        half = size // 2
        bob = math.sin(tick * 0.05 + cx) * 5
        py = cy + bob

        # Upward speed trail lines
        trail = pygame.Surface((size, 34), pygame.SRCALPHA)
        for ox in [-half + 8, 0, half - 8]:
            pygame.draw.line(trail, (*color, 120), (half + ox, 34), (half + ox, 4), 2)
        self._surface.blit(trail, (cx - half, py - half - 32))

        # Badge tile
        tile = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(tile, (18, 14, 36, 230), (0, 0, size, size), border_radius=10)
        pygame.draw.rect(tile, color, (0, 0, size, size), 2, border_radius=10)

        # Emoji/Icon
        emoji_char = S.GESTURE_EMOJIS.get(gesture, "")
        if emoji_char:
            efont = _get_emoji_font(int(size * 0.65))
            eglyph = efont.render(emoji_char, True, (255, 255, 255))
            tile.blit(eglyph, (size // 2 - eglyph.get_width() // 2, size // 2 - eglyph.get_height() // 2))

        self._surface.blit(tile, (cx - half, py - half))

    # ------------------------------------------------------------------
    # Danger Line & Hazard Strip
    # ------------------------------------------------------------------

    def draw_danger_line(self, tick: int = 0) -> None:
        """Full-width retro diagonal red-and-black hazard bar with warning text."""
        h_bar = 22
        y = self._danger_y - h_bar // 2

        # 1. Glowing hazard bar with diagonal red & black stripes
        hazard_surf = pygame.Surface((self._w, h_bar))
        hazard_surf.fill((160, 20, 20))
        # Draw 45-degree black stripes
        stripe_w = 20
        offset = (tick * 1.5) % (stripe_w * 2)
        for sx in range(int(-stripe_w * 2 + offset), self._w + stripe_w * 2, stripe_w * 2):
            pts = [(sx, h_bar), (sx + stripe_w, h_bar), (sx + stripe_w * 2, 0), (sx + stripe_w, 0)]
            pygame.draw.polygon(hazard_surf, (25, 5, 5), pts)

        # Bright neon red border top & bottom
        pygame.draw.line(hazard_surf, (255, 50, 50), (0, 0), (self._w, 0), 2)
        pygame.draw.line(hazard_surf, (255, 50, 50), (0, h_bar - 1), (self._w, h_bar - 1), 2)

        self._surface.blit(hazard_surf, (0, y))

        # 2. Glowing danger zone pill indicator in center
        font = _get_pixel_font(11)
        pulse = int(180 + 75 * math.sin(tick * 0.12))
        lbl = font.render("!  DANGER ZONE  !", True, (255, pulse, pulse))
        lw, lh = lbl.get_size()
        pill = pygame.Surface((lw + 28, lh + 10), pygame.SRCALPHA)
        pygame.draw.rect(pill, (20, 0, 0, 220), (0, 0, lw + 28, lh + 10), border_radius=6)
        pygame.draw.rect(pill, (255, 40, 40), (0, 0, lw + 28, lh + 10), 2, border_radius=6)
        pill.blit(lbl, (14, 5))

        self._surface.blit(pill, (self._w // 2 - (lw + 28) // 2, y + h_bar + 4))

    # ------------------------------------------------------------------
    # HUD (Score, Hearts, Combo)
    # ------------------------------------------------------------------

    def draw_hud(self, score: int, lives: int, combo: int) -> None:
        """Retro arcade HUD: digital score bezel, 16-bit pixel hearts, and combo burst."""
        # 1. Top-Left: Digital Score Panel
        sw, sh = 200, 56
        sx, sy = 24, 20
        score_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
        # Dark bezel box
        pygame.draw.rect(score_surf, (14, 12, 30, 240), (0, 0, sw, sh), border_radius=8)
        pygame.draw.rect(score_surf, (75, 50, 130), (0, 0, sw, sh), 2, border_radius=8)

        # "SCORE" label
        lbl_font = _get_pixel_font(10)
        lbl_txt = lbl_font.render("SCORE", True, S.NEON_CYAN)
        score_surf.blit(lbl_txt, (14, 8))

        # Digits: "000000" in glowing neon cyan
        val_font = _get_pixel_font(18)
        val_txt = val_font.render(f"{score:06d}", True, (255, 255, 255))
        score_surf.blit(val_txt, (14, 26))

        self._surface.blit(score_surf, (sx, sy))


        # 3. Combo Badge
        if combo >= 2:
            combo_font = _get_pixel_font(14)
            combo_txt = combo_font.render(f"x{combo} COMBO!", True, S.NEON_YELLOW)
            cw, ch = combo_txt.get_size()
            c_surf = pygame.Surface((cw + 24, ch + 12), pygame.SRCALPHA)
            pygame.draw.rect(c_surf, (30, 15, 60, 220), (0, 0, cw + 24, ch + 12), border_radius=8)
            pygame.draw.rect(c_surf, S.NEON_PINK, (0, 0, cw + 24, ch + 12), 2, border_radius=8)
            c_surf.blit(combo_txt, (12, 6))
            self._surface.blit(c_surf, (sx, sy + sh + 12))

    def _draw_pixel_hearts(self, lives: int) -> None:
        """Draw 3 chunky 16-bit pixel art red hearts spaced across top-center."""
        spacing = 42
        start_x = self._w // 2 - (S.INITIAL_LIVES * spacing) // 2
        y = 26

        for i in range(S.INITIAL_LIVES):
            cx = start_x + i * spacing + 12
            filled = i < lives
            # 16-bit pixel heart
            heart_surf = pygame.Surface((28, 26), pygame.SRCALPHA)
            if filled:
                col = (255, 35, 65)
                hi = (255, 140, 160)
                sh = (160, 15, 35)
                # Two lobes
                pygame.draw.circle(heart_surf, col, (8, 8), 7)
                pygame.draw.circle(heart_surf, col, (20, 8), 7)
                # Triangle body
                pygame.draw.polygon(heart_surf, col, [(1, 8), (27, 8), (14, 24)])
                # Highlight & shadow accents
                pygame.draw.circle(heart_surf, hi, (6, 6), 2)
                pygame.draw.polygon(heart_surf, sh, [(14, 24), (27, 8), (22, 16)])
            else:
                # Dark empty pixel heart
                col = (45, 25, 55)
                pygame.draw.circle(heart_surf, col, (8, 8), 7, 2)
                pygame.draw.circle(heart_surf, col, (20, 8), 7, 2)
                pygame.draw.polygon(heart_surf, col, [(1, 8), (27, 8), (14, 24)], 2)

            self._surface.blit(heart_surf, (cx, y))

    # ------------------------------------------------------------------
    # Webcam Mini-Preview (Gameplay HUD)
    # ------------------------------------------------------------------

    def draw_webcam_preview(self, frame: GestureFrame) -> None:
        """Top-right webcam preview in retro monitor frame with status indicator."""
        px, py = self._prev_x, self._prev_y
        pw, ph = self._prev_w, self._prev_h

        # Retro Monitor Frame with corner notches
        pygame.draw.rect(self._surface, (15, 12, 30), (px - 4, py - 4, pw + 8, ph + 8), border_radius=6)
        pygame.draw.rect(self._surface, (130, 70, 230), (px - 4, py - 4, pw + 8, ph + 8), 2, border_radius=6)

        # Video feed
        if frame.preview_frame is not None:
            try:
                rgb = cv2.cvtColor(frame.preview_frame, cv2.COLOR_BGR2RGB)
                pg_surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
                self._surface.blit(pg_surf, (px, py))
            except Exception:
                self._draw_cam_placeholder(px, py, pw, ph, "No Frame")
        else:
            msg = "No Camera" if not frame.camera_ok else "Waiting..."
            self._draw_cam_placeholder(px, py, pw, ph, msg)

        # Live Landmark Skeleton Overlay
        if frame.landmarks_2d and frame.camera_ok:
            self._draw_landmark_skeleton(frame.landmarks_2d, px, py)

        # Under-preview status bar with colored indicator dot
        bar_h = 24
        bar_y = py + ph + 4
        pygame.draw.rect(self._surface, (16, 12, 32), (px, bar_y, pw, bar_h), border_radius=5)
        pygame.draw.rect(self._surface, (60, 40, 110), (px, bar_y, pw, bar_h), 1, border_radius=5)

        dot_col = S.NEON_GREEN if frame.camera_ok else S.DANGER_COLOR
        pygame.draw.circle(self._surface, dot_col, (px + 12, bar_y + bar_h // 2), 4)

        stat_font = _get_pixel_font(8)
        if not frame.camera_ok:
            stat_str = "CAMERA ERROR"
            stat_col = S.DANGER_COLOR
        elif frame.gesture:
            label = S.GESTURE_LABELS.get(frame.gesture, frame.gesture).upper()
            pct = int(frame.confidence * 100)
            stat_str = f"{label} ({pct}%)"
            stat_col = S.NEON_GREEN
        else:
            stat_str = "GESTURE: READY"
            stat_col = (160, 160, 190)

        txt = stat_font.render(stat_str, True, stat_col)
        self._surface.blit(txt, (px + 22, bar_y + bar_h // 2 - txt.get_height() // 2))

    def _draw_cam_placeholder(self, x: int, y: int, w: int, h: int, msg: str) -> None:
        pygame.draw.rect(self._surface, (18, 14, 38), (x, y, w, h))
        font = _get_pixel_font(10)
        txt = font.render(msg, True, S.TEXT_DIM)
        self._surface.blit(txt, (x + w // 2 - txt.get_width() // 2, y + h // 2 - txt.get_height() // 2))

    def _draw_landmark_skeleton(
        self, landmarks: list[tuple[int, int]], ox: int, oy: int
    ) -> None:
        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4),
            (0, 5), (5, 6), (6, 7), (7, 8),
            (0, 9), (9, 10), (10, 11), (11, 12),
            (0, 13), (13, 14), (14, 15), (15, 16),
            (0, 17), (17, 18), (18, 19), (19, 20),
            (5, 9), (9, 13), (13, 17),
        ]
        for a, b in connections:
            if a < len(landmarks) and b < len(landmarks):
                ax, ay = landmarks[a][0] + ox, landmarks[a][1] + oy
                bx, by = landmarks[b][0] + ox, landmarks[b][1] + oy
                pygame.draw.line(self._surface, (*S.NEON_CYAN, 180), (ax, ay), (bx, by), 2)
        for lm in landmarks:
            pygame.draw.circle(self._surface, S.NEON_GREEN, (lm[0] + ox, lm[1] + oy), 3)

    # ------------------------------------------------------------------
    # Screen 1: Main Menu
    # ------------------------------------------------------------------

    def draw_menu(self, buttons: list[Button], best_score: int = 0) -> None:
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("1. MAIN MENU")
        mouse_pos = pygame.mouse.get_pos()

        # 1. 3D Chunky Retro Arcade Title: "HANDSIGN" + "RUSH"
        # "HANDSIGN" in Neon Cyan with 3D drop shadow
        title_font = _get_pixel_font(42)
        hs_top = title_font.render("HANDSIGN", True, S.NEON_CYAN)
        hs_sh = title_font.render("HANDSIGN", True, (15, 25, 65))
        tx = self._w // 2 - hs_top.get_width() // 2
        ty = 85
        # 3D shadow layers
        for off in range(5, 0, -1):
            self._surface.blit(hs_sh, (tx, ty + off))
        self._surface.blit(hs_top, (tx, ty))

        # "RUSH" in vibrant Golden Yellow / Orange with magenta sparks
        rush_font = _get_pixel_font(52)
        rush_top = rush_font.render("RUSH", True, (255, 215, 30))
        rush_sh = rush_font.render("RUSH", True, (160, 50, 0))
        rx = self._w // 2 - rush_top.get_width() // 2
        ry = 135
        for off in range(6, 0, -1):
            self._surface.blit(rush_sh, (rx, ry + off))
        self._surface.blit(rush_top, (rx, ry))

        # Magenta starburst spark accents (✦) around RUSH
        spark_font = _get_system_font(26, bold=True)
        sp_l = spark_font.render("✦", True, S.NEON_PINK)
        sp_r = spark_font.render("✦", True, S.NEON_PINK)
        self._surface.blit(sp_l, (rx - 36, ry + 12))
        self._surface.blit(sp_r, (rx + rush_top.get_width() + 14, ry + 12))

        # 2. Subtitle & Best Score Pill
        sub_font = _get_system_font(14, bold=False)
        sub1 = sub_font.render("Webcam-powered survival arcade", True, (220, 220, 240))
        self._surface.blit(sub1, (self._w // 2 - sub1.get_width() // 2, 210))

        if best_score > 0:
            best_font = _get_pixel_font(11)
            b_txt = best_font.render(f"★ HIGH SCORE: {best_score:06d} ★", True, S.NEON_YELLOW)
            bw, bh = b_txt.get_width() + 24, b_txt.get_height() + 8
            bx = self._w // 2 - bw // 2
            by = 236
            b_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pygame.draw.rect(b_surf, (20, 14, 40, 230), (0, 0, bw, bh), border_radius=10)
            pygame.draw.rect(b_surf, S.NEON_YELLOW, (0, 0, bw, bh), 1, border_radius=10)
            b_surf.blit(b_txt, (12, 4))
            self._surface.blit(b_surf, (bx, by))
        else:
            sub2 = sub_font.render("Destroy falling targets with your hands!", True, (150, 150, 180))
            self._surface.blit(sub2, (self._w // 2 - sub2.get_width() // 2, 235))

        # 3. Floating Neon Target Badges flanking the title
        self._draw_floating_target_badge("open_palm", tx - 80, 120, tick)
        self._draw_floating_target_badge("peace_sign", tx - 55, 220, tick + 30)
        self._draw_floating_target_badge("closed_fist", tx + hs_top.get_width() + 80, 130, tick + 60)
        self._draw_floating_target_badge("thumbs_up", tx + hs_top.get_width() + 60, 230, tick + 90)

        # 4. Buttons
        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))

        # 5. Animated Mascot on the stone platform ledge!
        self._draw_mascot(135, self._h - 74)

        # 6. Gesture legend pills at the bottom
        self._draw_gesture_legend(y=self._h - 52)

    def _draw_gesture_legend(self, y: int) -> None:
        font = _get_pixel_font(8)
        emoji_font = _get_emoji_font(13)
        items = []
        total_w = 0
        pad = 8

        for g in S.GESTURE_NAMES:
            emoji = S.GESTURE_EMOJIS.get(g, "")
            label = S.GESTURE_LABELS.get(g, g).upper()
            txt_w = font.size(label)[0] + 28
            items.append((g, emoji, label, txt_w))
            total_w += txt_w + 10
        total_w -= 10

        x = self._w // 2 - total_w // 2
        for g, emoji, label, pill_w in items:
            col = S.GESTURE_COLORS[g]
            rect = pygame.Rect(x, y, pill_w, 24)
            pygame.draw.rect(self._surface, (16, 12, 32, 220), rect, border_radius=12)
            pygame.draw.rect(self._surface, col, rect, 1, border_radius=12)

            eg = emoji_font.render(emoji, True, (255, 255, 255))
            self._surface.blit(eg, (x + pad, y + 4))

            tg = font.render(label, True, col)
            self._surface.blit(tg, (x + pad + 18, y + 7))

            x += pill_w + 10

    # ------------------------------------------------------------------
    # Screen 2: Camera Check Screen
    # ------------------------------------------------------------------

    def draw_camera_check(
        self,
        frame: GestureFrame,
        buttons: list[Button],
    ) -> None:
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("2. CAMERA CHECK")
        mouse_pos = pygame.mouse.get_pos()

        # Title & Subtitle
        title_font = _get_pixel_font(26)
        title = title_font.render("CAMERA CHECK", True, S.NEON_CYAN)
        self._surface.blit(title, (self._w // 2 - title.get_width() // 2, 45))

        sub_font = _get_system_font(16, bold=False)
        sub = sub_font.render("Make sure your webcam is working properly", True, (160, 160, 190))
        self._surface.blit(sub, (self._w // 2 - sub.get_width() // 2, 82))

        # Camera feed geometry (centered left-of-center to make room for Detected Gestures panel)
        pw, ph = 480, 360
        px = 140
        py = 115

        # Retro Monitor Frame with corner notches
        pygame.draw.rect(self._surface, (14, 10, 28), (px - 4, py - 4, pw + 8, ph + 8), border_radius=8)
        pygame.draw.rect(self._surface, (140, 75, 240), (px - 4, py - 4, pw + 8, ph + 8), 2, border_radius=8)

        # Video frame
        if frame.preview_frame is not None:
            try:
                rgb = cv2.cvtColor(frame.preview_frame, cv2.COLOR_BGR2RGB)
                prev_big = cv2.resize(rgb, (pw, ph))
                pg = pygame.surfarray.make_surface(np.transpose(prev_big, (1, 0, 2)))
                self._surface.blit(pg, (px, py))

                # Live hand landmark skeleton overlay
                if frame.landmarks_2d and frame.camera_ok:
                    scaled_lm = [
                        (int(lx * (pw / S.CAM_PREVIEW_W)), int(ly * (ph / S.CAM_PREVIEW_H)))
                        for lx, ly in frame.landmarks_2d
                    ]
                    self._draw_landmark_skeleton(scaled_lm, px, py)
            except Exception as e:
                print(f"[CameraCheck] Preview render error: {e}")
        else:
            pygame.draw.rect(self._surface, (20, 16, 42), (px, py, pw, ph), border_radius=6)
            msg = "INITIALIZING CAMERA FEED..." if frame.camera_ok else "NO CAMERA FEED DETECTED"
            font_ph = _get_pixel_font(12)
            txt_ph = font_ph.render(msg, True, S.TEXT_DIM)
            self._surface.blit(txt_ph, (px + pw // 2 - txt_ph.get_width() // 2, py + ph // 2 - txt_ph.get_height() // 2))

        # Status badge below camera
        badge_y = py + ph + 14
        if not frame.camera_ok:
            b_msg = "⚠  CAMERA DISCONNECTED"
            b_col = S.DANGER_COLOR
            b_bg = (60, 10, 10)
        elif frame.gesture:
            label = S.GESTURE_LABELS.get(frame.gesture, frame.gesture).upper()
            b_msg = f"✓  CAMERA READY!  ·  {label}"
            b_col = S.NEON_GREEN
            b_bg = (10, 50, 20)
        else:
            b_msg = "📹  CAMERA READY!"
            b_col = S.NEON_GREEN
            b_bg = (10, 50, 20)

        badge_font = _get_pixel_font(12)
        badge_txt = badge_font.render(b_msg, True, b_col)
        bw = badge_txt.get_width() + 32
        bh = 32
        bx = px + pw // 2 - bw // 2
        pygame.draw.rect(self._surface, b_bg, (bx, badge_y, bw, bh), border_radius=16)
        pygame.draw.rect(self._surface, b_col, (bx, badge_y, bw, bh), 2, border_radius=16)
        self._surface.blit(badge_txt, (bx + 16, badge_y + 8))

        # Right Side: "DETECTED GESTURES" panel (from reference mockup)
        self._draw_camera_check_gesture_panel(frame, x=670, y=py, w=470, h=ph)

        # Buttons (Continue, Retry, Back)
        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))

        # Animated mascot standing on stone ledge
        self._draw_mascot(100, self._h - 74)

    def _draw_camera_check_gesture_panel(
        self, frame: GestureFrame, x: int, y: int, w: int, h: int
    ) -> None:
        """Right-hand panel showing all gestures with live detection highlighting."""
        # Panel container
        pygame.draw.rect(self._surface, (16, 12, 34, 230), (x, y, w, h), border_radius=8)
        pygame.draw.rect(self._surface, (90, 55, 160), (x, y, w, h), 2, border_radius=8)

        # Header: "DETECTED GESTURES"
        head_font = _get_pixel_font(12)
        head_txt = head_font.render("DETECTED GESTURES", True, (240, 240, 255))
        self._surface.blit(head_txt, (x + w // 2 - head_txt.get_width() // 2, y + 16))
        pygame.draw.line(self._surface, (70, 45, 120), (x + 16, y + 38), (x + w - 16, y + 38), 1)

        # Gesture cards stacked vertically
        card_h = 44
        card_gap = 10
        card_y = y + 50
        font = _get_pixel_font(10)
        emoji_font = _get_emoji_font(18)

        for g in S.GESTURE_NAMES:
            color = S.GESTURE_COLORS[g]
            label = S.GESTURE_LABELS.get(g, g)
            emoji = S.GESTURE_EMOJIS.get(g, "")
            is_active = (frame.gesture == g and frame.camera_ok)

            card_rect = pygame.Rect(x + 16, card_y, w - 32, card_h)

            # Active glow & highlight when user holds this gesture!
            if is_active:
                pygame.draw.rect(self._surface, (*color, 60), card_rect, border_radius=8)
                pygame.draw.rect(self._surface, S.NEON_GREEN, card_rect, 2, border_radius=8)
            else:
                pygame.draw.rect(self._surface, (24, 18, 48), card_rect, border_radius=8)
                pygame.draw.rect(self._surface, (50, 35, 90), card_rect, 1, border_radius=8)

            # Colored Icon Badge box
            badge_rect = pygame.Rect(x + 24, card_y + 6, 32, 32)
            pygame.draw.rect(self._surface, color, badge_rect, border_radius=6)
            eg = emoji_font.render(emoji, True, (255, 255, 255))
            self._surface.blit(eg, (badge_rect.centerx - eg.get_width() // 2, badge_rect.centery - eg.get_height() // 2))

            # Label
            lbl_col = (255, 255, 255) if is_active else (200, 200, 220)
            txt = font.render(label, True, lbl_col)
            self._surface.blit(txt, (x + 68, card_y + 14))

            # Active checkmark
            if is_active:
                chk = font.render("ACTIVE", True, S.NEON_GREEN)
                self._surface.blit(chk, (x + w - 32 - chk.get_width() - 10, card_y + 14))

            card_y += card_h + card_gap

    # ------------------------------------------------------------------
    # Screen 3: Gameplay HUD Frame
    # ------------------------------------------------------------------

    def draw_playing_frame(
        self,
        score: int,
        lives: int,
        combo: int,
        gesture_frame: GestureFrame,
        tick: int,
        wave_number: int = 1,
        wave_progress: float = 0.0,
        wave_obj: int = 8,
        wave_destroyed: int = 0,
        toast_active: bool = False,
        toast_text: str = "",
        toast_sub: str = "",
        toast_alpha: float = 0.0,
    ) -> None:
        """Render all persistent HUD and overlay elements during active gameplay."""
        # Retro Screen Frame with "3. GAMEPLAY" badge
        self.draw_retro_frame("3. GAMEPLAY")

        # Subtle vertical dashed lane divider lines
        for lx in S.LANE_X:
            for dy in range(60, self._danger_y - 20, 24):
                pygame.draw.line(self._surface, (50, 35, 95), (lx, dy), (lx, dy + 12), 1)

        # Danger Zone hazard bar
        self.draw_danger_line(tick)

        # Mascot actively running/reacting along the bottom stone platform
        self._draw_mascot(int(self.mascot.x), self._h - 74)

        # HUD Score & Hearts
        self.draw_hud(score, lives, combo)

        # Wave HUD: wave number pill + progress bar
        self.draw_wave_hud(wave_number, wave_progress, wave_obj, wave_destroyed, tick)

        # Webcam preview in top-right
        self.draw_webcam_preview(gesture_frame)

        # Camera disconnected warning banner
        if not gesture_frame.camera_ok:
            self._draw_cam_warning()

        # Small wave-start toast (non-blocking, near top, fades out)
        if toast_active and toast_alpha > 0.01:
            self.draw_wave_toast(toast_text, toast_sub, toast_alpha)

    def _draw_cam_warning(self) -> None:
        font = _get_pixel_font(10)
        txt = font.render("! CAMERA DISCONNECTED - GESTURE CONTROL SUSPENDED !", True, S.DANGER_COLOR)
        w, h = txt.get_size()
        strip = pygame.Surface((w + 24, h + 12), pygame.SRCALPHA)
        strip.fill((80, 0, 0, 210))
        pygame.draw.rect(strip, S.DANGER_COLOR, strip.get_rect(), 2, border_radius=6)
        self._surface.blit(strip, (self._w // 2 - (w + 24) // 2, self._h - 60))
        self._surface.blit(txt, (self._w // 2 - w // 2, self._h - 54))

    # ------------------------------------------------------------------
    # Wave HUD: Wave number pill and target progress bar
    # ------------------------------------------------------------------

    def draw_wave_hud(
        self,
        wave_number: int,
        progress: float,
        obj_total: int,
        destroyed: int,
        tick: int = 0,
    ) -> None:
        """
        Draw the wave-number pill (top-center-right) and a
        horizontal progress bar under the score box.
        """
        # --- Wave number pill (top-right area, left of webcam preview) ---
        pill_w, pill_h = 130, 38
        pill_x = self._prev_x - pill_w - 14   # just left of camera preview
        pill_y = 20

        pill_surf = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
        pygame.draw.rect(pill_surf, (14, 10, 30, 240), (0, 0, pill_w, pill_h), border_radius=8)
        pygame.draw.rect(pill_surf, S.NEON_VIOLET, (0, 0, pill_w, pill_h), 2, border_radius=8)

        wv_font = _get_pixel_font(9)
        wv_lbl = wv_font.render("WAVE", True, S.NEON_VIOLET)
        pill_surf.blit(wv_lbl, (12, 6))

        wv_num_font = _get_pixel_font(16)
        wv_num = wv_num_font.render(str(wave_number), True, S.NEON_CYAN)
        pill_surf.blit(wv_num, (pill_w - wv_num.get_width() - 12, 10))

        self._surface.blit(pill_surf, (pill_x, pill_y))

    # ------------------------------------------------------------------
    # Wave toast — small non-blocking notification (replaces the old
    # large central banner).  Fades out over ~0.7 seconds.
    # ------------------------------------------------------------------

    def draw_wave_toast(self, text: str, sub: str, alpha: float) -> None:
        """Small toast notification near the top center. alpha 0–1 controls fade."""
        if alpha <= 0.01:
            return

        a8 = max(0, min(255, int(alpha * 255)))

        # Pill dimensions
        font_main = _get_pixel_font(14)
        font_sub  = _get_system_font(12, bold=False)

        main_surf = font_main.render(text, True, S.NEON_CYAN)
        sub_surf  = font_sub.render(sub, True, (200, 200, 230)) if sub else None

        pill_w = max(main_surf.get_width() + (sub_surf.get_width() if sub_surf else 0) + 50, 220)
        pill_h = 36
        pill_x = self._w // 2 - pill_w // 2
        pill_y = 62   # below the retro frame badge, above gameplay area

        # Background pill with alpha
        pill = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
        pygame.draw.rect(pill, (10, 8, 28, int(210 * alpha)), (0, 0, pill_w, pill_h), border_radius=10)
        pygame.draw.rect(pill, (*S.NEON_VIOLET, a8), (0, 0, pill_w, pill_h), 2, border_radius=10)
        self._surface.blit(pill, (pill_x, pill_y))

        # Main text (left side of pill)
        main_surf.set_alpha(a8)
        self._surface.blit(main_surf, (pill_x + 14, pill_y + pill_h // 2 - main_surf.get_height() // 2))

        # Sub text (right side)
        if sub_surf:
            # Separator dot
            dot_x = pill_x + 14 + main_surf.get_width() + 10
            dot_y = pill_y + pill_h // 2
            dot_col = (*S.NEON_CYAN[:3], a8)
            ds = pygame.Surface((4, 4), pygame.SRCALPHA)
            pygame.draw.circle(ds, dot_col, (2, 2), 2)
            self._surface.blit(ds, (dot_x, dot_y - 2))

            sub_surf.set_alpha(a8)
            self._surface.blit(sub_surf, (dot_x + 10, pill_y + pill_h // 2 - sub_surf.get_height() // 2))

    # ------------------------------------------------------------------
    # Countdown Screen
    # ------------------------------------------------------------------

    def draw_countdown(self, count: int, progress: float) -> None:
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("COUNTDOWN")

        scale = 1.0 + (1.0 - progress) * 0.4
        font_size = int(80 * scale)
        font = _get_pixel_font(font_size)

        text_str = str(count) if count > 0 else "GO!"
        color = S.NEON_CYAN if count > 0 else S.NEON_GREEN

        txt = font.render(text_str, True, color)
        # Drop shadow
        sh = font.render(text_str, True, (15, 10, 35))
        tx = self._w // 2 - txt.get_width() // 2
        ty = self._h // 2 - txt.get_height() // 2

        self._surface.blit(sh, (tx + 4, ty + 4))
        self._surface.blit(txt, (tx, ty))

    # ------------------------------------------------------------------
    # Pause Overlay
    # ------------------------------------------------------------------

    def draw_pause_overlay(self, buttons: list[Button]) -> None:
        mouse_pos = pygame.mouse.get_pos()

        # Dim screen
        dim = pygame.Surface((self._w, self._h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 180))
        self._surface.blit(dim, (0, 0))

        font = _get_pixel_font(36)
        txt = font.render("PAUSED", True, S.NEON_VIOLET)
        self._surface.blit(txt, (self._w // 2 - txt.get_width() // 2, self._h // 2 - 120))

        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))

    # ------------------------------------------------------------------
    # Game Over Screen
    # ------------------------------------------------------------------

    def draw_game_over(
        self, score: int, best: int, buttons: list[Button], reached_wave: int = 1
    ) -> None:
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("GAME OVER")
        mouse_pos = pygame.mouse.get_pos()

        # "GAME OVER" in bold flashing crimson/neon red
        go_font = _get_pixel_font(42)
        go_top = go_font.render("GAME OVER", True, S.DANGER_COLOR)
        go_sh = go_font.render("GAME OVER", True, (60, 0, 10))
        tx = self._w // 2 - go_top.get_width() // 2
        ty = 90
        for off in range(4, 0, -1):
            self._surface.blit(go_sh, (tx, ty + off))
        self._surface.blit(go_top, (tx, ty))

        # Score results box (taller to fit wave row)
        bw, bh = 380, 168
        bx = self._w // 2 - bw // 2
        by = 175
        pygame.draw.rect(self._surface, (18, 14, 38, 240), (bx, by, bw, bh), border_radius=10)
        pygame.draw.rect(self._surface, (120, 60, 200), (bx, by, bw, bh), 2, border_radius=10)

        score_font = _get_pixel_font(18)
        s_txt = score_font.render(f"SCORE: {score:06d}", True, S.NEON_CYAN)
        self._surface.blit(s_txt, (bx + bw // 2 - s_txt.get_width() // 2, by + 22))

        best_font = _get_pixel_font(14)
        b_txt = best_font.render(f"BEST:  {best:06d}", True, S.NEON_YELLOW)
        self._surface.blit(b_txt, (bx + bw // 2 - b_txt.get_width() // 2, by + 58))

        wave_font = _get_pixel_font(12)
        w_txt = wave_font.render(f"WAVE REACHED:  {reached_wave}", True, S.NEON_VIOLET)
        self._surface.blit(w_txt, (bx + bw // 2 - w_txt.get_width() // 2, by + 92))

        if score >= best and score > 0:
            badge_font = _get_pixel_font(10)
            nb = badge_font.render("★ NEW BEST RECORD! ★", True, S.NEON_GREEN)
            self._surface.blit(nb, (bx + bw // 2 - nb.get_width() // 2, by + 130))

        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))

        # Mascot on stone ledge (cleanly separated on bottom-left away from score & buttons)
        self._draw_mascot(135, self._h - 74)


    # ------------------------------------------------------------------
    # How To Play Screen
    # ------------------------------------------------------------------

    def draw_how_to_play(self, buttons: list[Button]) -> None:
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("HOW TO PLAY")
        mouse_pos = pygame.mouse.get_pos()

        title_font = _get_pixel_font(26)
        title = title_font.render("HOW TO PLAY", True, S.NEON_CYAN)
        self._surface.blit(title, (self._w // 2 - title.get_width() // 2, 45))

        lines = [
            "Targets fall from the top of the screen in two vertical lanes.",
            "Show the matching hand gesture to your webcam to destroy each target.",
            "",
            "• Hold the gesture steadily for ~0.4 seconds to fire.",
            "• Chain successful clears to build high COMBO score multipliers!",
            "• If a target crosses the DANGER ZONE, you lose 1 life (start with 3).",
            "• Targets fall faster as your score climbs. Test your reflexes!",
            "",
            "CONTROLS:  Esc = Pause / Back    Alt+F4 = Quit Game",
        ]
        line_font = _get_system_font(16, bold=False)
        for i, line in enumerate(lines):
            col = (240, 240, 255) if line.startswith("•") else ((160, 160, 190) if not line.startswith("CONTROLS") else S.NEON_YELLOW)
            surf = line_font.render(line, True, col)
            self._surface.blit(surf, (self._w // 2 - surf.get_width() // 2, 100 + i * 26))

        # Gesture grid at bottom
        gx = self._w // 2 - (len(S.GESTURE_NAMES) * 110) // 2
        gy = 370
        from target import get_icon
        for i, g in enumerate(S.GESTURE_NAMES):
            cx = gx + i * 110
            # Tile frame
            pygame.draw.rect(self._surface, (20, 16, 42), (cx + 10, gy, 80, 80), border_radius=8)
            pygame.draw.rect(self._surface, S.GESTURE_COLORS[g], (cx + 10, gy, 80, 80), 2, border_radius=8)

            icon = get_icon(g, 60)
            self._surface.blit(icon, (cx + 20, gy + 10))

            lbl_font = _get_pixel_font(8)
            lbl = lbl_font.render(S.GESTURE_LABELS[g].upper(), True, S.GESTURE_COLORS[g])
            self._surface.blit(lbl, (cx + 50 - lbl.get_width() // 2, gy + 90))

        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))

        # Mascot on stone ledge
        self._draw_mascot(110, self._h - 74)

    # ------------------------------------------------------------------
    # Quick Mute Button & Audio Settings Screen
    # ------------------------------------------------------------------

    def draw_mute_button(self, rect: pygame.Rect, muted: bool, hovered: bool = False) -> None:
        """Draw small retro speaker icon button for quick mute/unmute."""
        bg = (55, 20, 25) if muted else ((50, 40, 95) if hovered else (30, 24, 60))
        border = S.DANGER_COLOR if muted else (S.NEON_CYAN if hovered else (80, 60, 150))

        pygame.draw.rect(self._surface, bg, rect, border_radius=6)
        pygame.draw.rect(self._surface, border, rect, 2, border_radius=6)

        emoji_font = _get_emoji_font(16)
        icon_str = "🔇" if muted else "🔊"
        icon_surf = emoji_font.render(icon_str, True, (255, 255, 255))
        self._surface.blit(
            icon_surf,
            (rect.centerx - icon_surf.get_width() // 2, rect.centery - icon_surf.get_height() // 2),
        )

    def draw_audio_settings(
        self,
        sliders: list[Slider],
        buttons: list[Button],
        muted: bool,
    ) -> None:
        """Render retro arcade Audio Settings panel."""
        tick = pygame.time.get_ticks() // 16
        self.draw_background(tick)
        self.draw_retro_frame("AUDIO SETTINGS")
        mouse_pos = pygame.mouse.get_pos()

        # Title
        title_font = _get_pixel_font(26)
        title = title_font.render("AUDIO SETTINGS", True, S.NEON_CYAN)
        self._surface.blit(title, (self._w // 2 - title.get_width() // 2, 45))

        sub_font = _get_system_font(16, bold=False)
        sub = sub_font.render("Adjust retro arcade volumes and sound balance", True, (160, 160, 190))
        self._surface.blit(sub, (self._w // 2 - sub.get_width() // 2, 82))

        # Settings Card Box
        card_w, card_h = 580, 440
        card_x = self._w // 2 - card_w // 2
        card_y = 120
        pygame.draw.rect(self._surface, (18, 14, 38, 240), (card_x, card_y, card_w, card_h), border_radius=10)
        pygame.draw.rect(self._surface, (120, 60, 200), (card_x, card_y, card_w, card_h), 2, border_radius=10)

        # Mute status banner inside card
        stat_col = S.DANGER_COLOR if muted else S.NEON_GREEN
        stat_msg = "● AUDIO IS MUTED" if muted else "● AUDIO ACTIVE"
        stat_font = _get_pixel_font(9)
        stat_txt = stat_font.render(stat_msg, True, stat_col)
        self._surface.blit(stat_txt, (card_x + 30, card_y + 22))

        # Draw sliders
        for s in sliders:
            s.draw(self._surface)

        # Draw buttons
        for btn in buttons:
            btn.draw(self._surface, btn.is_hovered(mouse_pos))


# ---------------------------------------------------------------------------
# Slider Component
# ---------------------------------------------------------------------------

class Slider:
    """An interactive retro arcade slider for volume controls."""

    def __init__(self, rect: pygame.Rect, label: str, value: float = 0.8) -> None:
        self.rect = rect
        self.label = label
        self.value = max(0.0, min(1.0, value))
        self.dragging = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            expanded = self.rect.inflate(16, 20)
            if expanded.collidepoint(event.pos):
                self.dragging = True
                self._update_val(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.dragging = False
                return True
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self._update_val(event.pos[0])
            return True
        return False

    def _update_val(self, mx: int) -> None:
        rel = (mx - self.rect.x) / max(1, self.rect.width)
        self.value = max(0.0, min(1.0, rel))

    def draw(self, surface: pygame.Surface) -> None:
        # Label and percentage
        font = _get_pixel_font(10)
        lbl_surf = font.render(self.label, True, (220, 220, 240))
        pct_str = f"{int(round(self.value * 100))}%"
        pct_surf = font.render(pct_str, True, S.NEON_CYAN)

        surface.blit(lbl_surf, (self.rect.x, self.rect.y - 20))
        surface.blit(pct_surf, (self.rect.right - pct_surf.get_width(), self.rect.y - 20))

        # Track background
        pygame.draw.rect(surface, (14, 10, 28), self.rect, border_radius=4)
        pygame.draw.rect(surface, (60, 40, 100), self.rect, 1, border_radius=4)

        # Filled track portion
        fill_w = int(self.rect.width * self.value)
        if fill_w > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_w, self.rect.height)
            pygame.draw.rect(surface, S.NEON_CYAN, fill_rect, border_radius=4)

        # Draggable thumb
        thumb_x = self.rect.x + fill_w
        thumb_rect = pygame.Rect(thumb_x - 7, self.rect.y - 5, 14, self.rect.height + 10)
        pygame.draw.rect(surface, (255, 255, 255), thumb_rect, border_radius=3)
        pygame.draw.rect(surface, (10, 8, 20), thumb_rect, 2, border_radius=3)

