"""
main.py — Entry point for HandSign Rush.

Manages the application lifecycle: Pygame init/quit, state machine routing,
HandTracker lifecycle, Audio playback & sound triggers, and the main game loop.
"""

from __future__ import annotations

import sys
import time
from enum import Enum, auto

import pygame

import audio_manager
import settings as S
from game import GameState
from hand_tracker import SharedGestureState, create_tracker
from mascot import MascotState
from ui import Button, Slider, UIRenderer


# ---------------------------------------------------------------------------
# Application state machine
# ---------------------------------------------------------------------------

class AppState(Enum):
    MENU = auto()
    HOW_TO_PLAY = auto()
    AUDIO_SETTINGS = auto()
    CAMERA_CHECK = auto()
    COUNTDOWN = auto()
    PLAYING = auto()
    PAUSED = auto()
    GAME_OVER = auto()
    QUIT = auto()


# ---------------------------------------------------------------------------
# Button factory helpers
# ---------------------------------------------------------------------------

def _centre_button(
    label: str,
    y: int,
    w: int = 260,
    h: int = 52,
    centre_x: int | None = None,
    cx: int | None = None,
    display_label: str | None = None,
    style: str = "auto",
) -> Button:
    chosen_x = cx if cx is not None else (centre_x if centre_x is not None else S.WINDOW_W // 2)
    rect = pygame.Rect(chosen_x - w // 2, y, w, h)
    return Button(rect, label, display_label=display_label, style=style)


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class HandSignRushApp:
    """Owns all top-level resources, audio, and runs the main loop."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(S.WINDOW_TITLE)
        self._screen = pygame.display.set_mode((S.WINDOW_W, S.WINDOW_H))
        self._clock = pygame.time.Clock()

        # Initialize audio system & start menu theme
        audio_manager.initialize_audio()
        audio_manager.play_music("menu_theme", loop=True, fade_ms=400)

        # Shared gesture state (thread-safe)
        self._shared = SharedGestureState()

        # Background capture worker
        self._tracker = create_tracker(self._shared)
        self._tracker.start()

        # Rendering
        self._ui = UIRenderer(self._screen)

        # Game logic
        self._game = GameState(self._shared)

        # Application state
        self._state = AppState.MENU

        # Countdown state
        self._countdown_value: int = S.COUNTDOWN_START
        self._countdown_timer: float = 0.0

        # Buttons per screen
        self._menu_buttons: list[Button] = self._make_menu_buttons()
        self._pause_buttons: list[Button] = self._make_pause_buttons()
        self._gameover_buttons: list[Button] = self._make_gameover_buttons()
        self._camcheck_buttons: list[Button] = self._make_camcheck_buttons()
        self._howtoplay_buttons: list[Button] = self._make_howtoplay_buttons()

        # Audio settings sliders and buttons
        self._audio_sliders, self._audio_buttons = self._make_audio_settings_elements()

        # Quick mute button (always visible in top right)
        self._mute_rect = pygame.Rect(S.WINDOW_W - 58, 14, 38, 34)

        # Hover tracking for button_hover SFX
        self._last_hovered_button: Button | None = None

        # Camera state tracking for camera chime SFX
        self._prev_camera_ok: bool = False

        # Tick counter for animated effects
        self._tick: int = 0

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop. Runs until state is QUIT."""
        try:
            while self._state != AppState.QUIT:
                dt = self._clock.tick(S.FPS) / 1000.0
                dt = min(dt, 0.1)
                self._tick += 1

                events = pygame.event.get()
                self._handle_global_events(events)

                if self._state != AppState.QUIT:
                    self._update(dt, events)
                    self._draw()
                    pygame.display.flip()
        finally:
            self._shutdown()

    # ------------------------------------------------------------------
    # Global event handling (window close, quick mute)
    # ------------------------------------------------------------------

    def _handle_global_events(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.QUIT:
                self._state = AppState.QUIT
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Check quick mute button click
                if self._mute_rect.collidepoint(event.pos):
                    audio_manager.toggle_mute()
                    audio_manager.play_sfx("button_click")

    # ------------------------------------------------------------------
    # Button hover SFX helper
    # ------------------------------------------------------------------

    def _update_hover_sfx(self, buttons: list[Button], mouse_pos: tuple[int, int]) -> None:
        current_hovered: Button | None = None
        for b in buttons:
            if b.is_hovered(mouse_pos):
                current_hovered = b
                break

        if current_hovered is not None and current_hovered is not self._last_hovered_button:
            audio_manager.play_sfx("button_hover")

        self._last_hovered_button = current_hovered

    # ------------------------------------------------------------------
    # Update — routes to per-state logic
    # ------------------------------------------------------------------

    def _update(self, dt: float, events: list[pygame.event.Event]) -> None:
        state = self._state
        mouse_pos = pygame.mouse.get_pos()

        # Update mascot animation timer
        self._ui.mascot.update(dt)

        if state == AppState.MENU:
            self._update_hover_sfx(self._menu_buttons, mouse_pos)
            self._update_menu(events)
        elif state == AppState.HOW_TO_PLAY:
            self._update_hover_sfx(self._howtoplay_buttons, mouse_pos)
            self._update_how_to_play(events)
        elif state == AppState.AUDIO_SETTINGS:
            self._update_hover_sfx(self._audio_buttons, mouse_pos)
            self._update_audio_settings(events)
        elif state == AppState.CAMERA_CHECK:
            self._update_hover_sfx(self._camcheck_buttons, mouse_pos)
            self._update_camera_check(dt, events)
        elif state == AppState.COUNTDOWN:
            self._update_countdown(dt, events)
        elif state == AppState.PLAYING:
            self._update_playing(dt, events)
        elif state == AppState.PAUSED:
            self._update_hover_sfx(self._pause_buttons, mouse_pos)
            self._update_paused(events)
        elif state == AppState.GAME_OVER:
            self._update_hover_sfx(self._gameover_buttons, mouse_pos)
            self._update_game_over(events)

    # ------------------------------------------------------------------
    # Draw — routes to per-state rendering
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        state = self._state

        if state == AppState.MENU:
            self._ui.draw_menu(self._menu_buttons, best_score=self._game.best_score)

        elif state == AppState.HOW_TO_PLAY:
            self._ui.draw_how_to_play(self._howtoplay_buttons)

        elif state == AppState.AUDIO_SETTINGS:
            self._ui.draw_audio_settings(
                self._audio_sliders,
                self._audio_buttons,
                audio_manager.get_audio_manager().muted,
            )

        elif state == AppState.CAMERA_CHECK:
            frame = self._shared.read()
            self._ui.draw_camera_check(frame, self._camcheck_buttons)

        elif state == AppState.COUNTDOWN:
            self._ui.draw_background(self._tick)
            progress = min(1.0, self._countdown_timer / S.COUNTDOWN_STEP_DURATION)
            self._ui.draw_countdown(self._countdown_value, progress)

        elif state == AppState.PLAYING:
            self._ui.draw_background(self._tick)
            self._game.draw(self._screen)
            frame = self._shared.read()
            wm = self._game.wave_manager
            self._ui.draw_playing_frame(
                self._game.score,
                self._game.lives,
                self._game.combo,
                frame,
                self._tick,
                wave_number=wm.wave_number,
                wave_progress=wm.progress_fraction,
                wave_obj=wm.objective_count,
                wave_destroyed=wm.destroyed_this_wave,
                toast_active=wm.toast.active,
                toast_text=wm.toast.text,
                toast_sub=wm.toast.sub,
                toast_alpha=wm.toast.alpha_fraction,
            )

        elif state == AppState.PAUSED:
            self._ui.draw_background(self._tick)
            self._game.draw(self._screen)
            frame = self._shared.read()
            wm = self._game.wave_manager
            self._ui.draw_playing_frame(
                self._game.score,
                self._game.lives,
                self._game.combo,
                frame,
                self._tick,
                wave_number=wm.wave_number,
                wave_progress=wm.progress_fraction,
                wave_obj=wm.objective_count,
                wave_destroyed=wm.destroyed_this_wave,
            )
            self._ui.draw_pause_overlay(self._pause_buttons)

        elif state == AppState.GAME_OVER:
            self._ui.draw_game_over(
                self._game.score,
                self._game.best_score,
                self._gameover_buttons,
                reached_wave=self._game.wave_manager.wave_number,
            )

        # Draw quick speaker mute button across all screens
        mouse_pos = pygame.mouse.get_pos()
        self._ui.draw_mute_button(
            self._mute_rect,
            audio_manager.get_audio_manager().muted,
            self._mute_rect.collidepoint(mouse_pos),
        )

    # ------------------------------------------------------------------
    # Per-state update logic
    # ------------------------------------------------------------------

    def _update_menu(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                self._state = AppState.QUIT
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for b in self._menu_buttons:
                    if b.is_hovered(pos):
                        if b.label == "Play":
                            audio_manager.play_sfx("game_start")
                            self._enter_camera_check()
                        elif b.label == "How to Play":
                            audio_manager.play_sfx("button_click")
                            self._state = AppState.HOW_TO_PLAY
                        elif b.label == "Audio Settings":
                            audio_manager.play_sfx("button_click")
                            self._state = AppState.AUDIO_SETTINGS
                        elif b.label == "Quit":
                            audio_manager.play_sfx("button_click")
                            self._state = AppState.QUIT

    def _update_how_to_play(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type in (pygame.KEYDOWN,) and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                self._enter_menu()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for btn in self._howtoplay_buttons:
                    if btn.is_hovered(pos) and btn.label == "Back":
                        audio_manager.play_sfx("button_click")
                        self._enter_menu()

    def _update_audio_settings(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                self._enter_menu()

            # Handle slider events (drag / click)
            for s in self._audio_sliders:
                if s.handle_event(event):
                    if s.label == "MASTER VOLUME":
                        audio_manager.set_master_volume(s.value)
                    elif s.label == "MUSIC VOLUME":
                        audio_manager.set_music_volume(s.value)
                    elif s.label == "SOUND EFFECTS VOLUME":
                        audio_manager.set_sfx_volume(s.value)

            # Handle buttons
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for btn in self._audio_buttons:
                    if btn.is_hovered(pos):
                        if btn.label == "Mute Toggle":
                            is_muted = audio_manager.toggle_mute()
                            btn.display_label = "MUTE ALL: ON" if is_muted else "MUTE ALL: OFF"
                            audio_manager.play_sfx("button_click")
                        elif btn.label == "Test Sound":
                            audio_manager.play_sfx("level_up")
                        elif btn.label == "Back":
                            audio_manager.play_sfx("button_click")
                            self._enter_menu()

    def _update_camera_check(
        self, dt: float, events: list[pygame.event.Event]
    ) -> None:
        frame = self._shared.read()

        # Play camera_ready chime when camera first connects
        if frame.camera_ok and not self._prev_camera_ok:
            audio_manager.play_sfx("camera_ready")
            self._ui.mascot.trigger_victory(return_to=MascotState.IDLE)
        elif not frame.camera_ok and self._prev_camera_ok:
            audio_manager.play_sfx("camera_error")
            self._ui.mascot.trigger_hurt(return_to=MascotState.IDLE)
        self._prev_camera_ok = frame.camera_ok

        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                self._state = AppState.MENU
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for btn in self._camcheck_buttons:
                    if btn.is_hovered(pos):
                        if btn.label == "Continue":
                            audio_manager.play_sfx("game_start")
                            self._enter_countdown()
                        elif btn.label == "Retry":
                            audio_manager.play_sfx("button_click")
                            if hasattr(self._tracker, "restart"):
                                self._tracker.restart()
                        elif btn.label == "Back":
                            audio_manager.play_sfx("button_click")
                            self._enter_menu()

        # Auto-advance if camera is ready and user presses Enter
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                if frame.camera_ok:
                    audio_manager.play_sfx("game_start")
                    self._enter_countdown()

    def _update_countdown(
        self, dt: float, events: list[pygame.event.Event]
    ) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                audio_manager.play_music("menu_theme", loop=True, fade_ms=300)
                self._state = AppState.MENU
                return

        self._countdown_timer += dt
        if self._countdown_timer >= S.COUNTDOWN_STEP_DURATION:
            self._countdown_timer = 0.0
            self._countdown_value -= 1
            if self._countdown_value == 0:
                audio_manager.play_sfx("game_start")
            elif self._countdown_value < 0:
                self._state = AppState.PLAYING

    def _update_playing(
        self, dt: float, events: list[pygame.event.Event]
    ) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    audio_manager.play_sfx("button_click")
                    audio_manager.get_audio_manager().pause_music()
                    self._state = AppState.PAUSED
                    return

        self._game.update(dt)

        # Read wave events after update
        wm = self._game.wave_manager
        if wm.event.wave_complete:
            audio_manager.play_sfx("level_up")

        # Mascot gameplay patrol traversal
        self._ui.mascot.update_gameplay_patrol(dt)

        # Mascot gameplay reactions
        if getattr(self._game, "target_destroyed_this_frame", False):
            self._ui.mascot.trigger_jump(return_to=MascotState.RUN)
            self._game.target_destroyed_this_frame = False
        elif getattr(self._game, "life_lost_this_frame", False):
            self._ui.mascot.trigger_hurt(return_to=MascotState.RUN)
            self._game.life_lost_this_frame = False

        if self._game.is_game_over:
            audio_manager.stop_music(fade_ms=200)
            audio_manager.play_sfx("game_over")
            if self._game.score >= self._game.best_score and self._game.score > 0:
                self._ui.mascot.trigger_victory(return_to=MascotState.IDLE)
            else:
                self._ui.mascot.trigger_hurt(return_to=MascotState.IDLE)
            self._state = AppState.GAME_OVER

    def _update_paused(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                audio_manager.get_audio_manager().unpause_music()
                self._state = AppState.PLAYING
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for btn in self._pause_buttons:
                    if btn.is_hovered(pos):
                        if btn.label == "Resume":
                            audio_manager.play_sfx("button_click")
                            audio_manager.get_audio_manager().unpause_music()
                            self._state = AppState.PLAYING
                        elif btn.label == "Main Menu":
                            audio_manager.play_sfx("button_click")
                            audio_manager.play_music("menu_theme", loop=True, fade_ms=300)
                            self._enter_menu()

    def _update_game_over(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                audio_manager.play_sfx("button_click")
                audio_manager.play_music("menu_theme", loop=True, fade_ms=300)
                self._enter_menu()
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                for btn in self._gameover_buttons:
                    if btn.is_hovered(pos):
                        if btn.label == "Play Again":
                            audio_manager.play_sfx("game_start")
                            self._enter_countdown_from_gameover()
                        elif btn.label == "Main Menu":
                            audio_manager.play_sfx("button_click")
                            audio_manager.play_music("menu_theme", loop=True, fade_ms=300)
                            self._enter_menu()

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _enter_menu(self) -> None:
        self._ui.mascot.trigger_idle()
        self._state = AppState.MENU

    def _enter_camera_check(self) -> None:
        if not self._tracker.is_running():
            self._tracker.start()
        self._ui.mascot.trigger_idle()
        self._state = AppState.CAMERA_CHECK

    def _enter_countdown(self) -> None:
        self._countdown_value = S.COUNTDOWN_START
        self._countdown_timer = 0.0
        self._game.reset()
        self._ui.mascot.trigger_run()
        audio_manager.play_music("gameplay_theme", loop=True, fade_ms=500)
        self._state = AppState.COUNTDOWN

    def _enter_countdown_from_gameover(self) -> None:
        self._countdown_value = S.COUNTDOWN_START
        self._countdown_timer = 0.0
        self._game.reset()
        self._ui.mascot.trigger_run()
        audio_manager.play_music("gameplay_theme", loop=True, fade_ms=500)
        self._state = AppState.COUNTDOWN

    # ------------------------------------------------------------------
    # Button and slider factories
    # ------------------------------------------------------------------

    def _make_menu_buttons(self) -> list[Button]:
        cx = S.WINDOW_W // 2
        return [
            _centre_button("Play",           290, w=280, h=52, cx=cx, display_label="▶  PLAY",           style="yellow"),
            _centre_button("How to Play",    354, w=280, h=52, cx=cx, display_label="📖  HOW TO PLAY",    style="purple"),
            _centre_button("Audio Settings", 418, w=280, h=52, cx=cx, display_label="⚙  AUDIO SETTINGS", style="purple"),
            _centre_button("Quit",           482, w=280, h=52, cx=cx, display_label="✕  QUIT",           style="navy"),
        ]

    def _make_pause_buttons(self) -> list[Button]:
        cx = S.WINDOW_W // 2
        return [
            _centre_button("Resume",     S.WINDOW_H // 2 - 20, w=240, h=50, cx=cx, display_label="▶  RESUME",    style="yellow"),
            _centre_button("Main Menu",  S.WINDOW_H // 2 + 50, w=240, h=50, cx=cx, display_label="☰  MAIN MENU", style="purple"),
        ]

    def _make_gameover_buttons(self) -> list[Button]:
        cx = S.WINDOW_W // 2
        return [
            _centre_button("Play Again", 350, w=260, h=52, cx=cx, display_label="▶  PLAY AGAIN", style="yellow"),
            _centre_button("Main Menu",  420, w=260, h=52, cx=cx, display_label="☰  MAIN MENU",  style="purple"),
        ]

    def _make_camcheck_buttons(self) -> list[Button]:
        bw, bh = 190, 50
        y = 565
        return [
            Button(pygame.Rect(640 - 310, y, bw, bh), "Continue", display_label="CONTINUE", style="yellow"),
            Button(pygame.Rect(640 - 95,  y, bw, bh), "Retry",    display_label="RETRY",    style="purple"),
            Button(pygame.Rect(640 + 120, y, bw, bh), "Back",     display_label="BACK",     style="navy"),
        ]

    def _make_howtoplay_buttons(self) -> list[Button]:
        cx = S.WINDOW_W // 2
        return [_centre_button("Back", S.WINDOW_H - 110, w=220, h=48, cx=cx, display_label="◀  BACK", style="navy")]

    def _make_audio_settings_elements(self) -> tuple[list[Slider], list[Button]]:
        cx = S.WINDOW_W // 2
        mgr = audio_manager.get_audio_manager()

        sliders = [
            Slider(pygame.Rect(cx - 240, 185, 480, 12), "MASTER VOLUME", mgr.master_volume),
            Slider(pygame.Rect(cx - 240, 255, 480, 12), "MUSIC VOLUME",  mgr.music_volume),
            Slider(pygame.Rect(cx - 240, 325, 480, 12), "SOUND EFFECTS VOLUME", mgr.sfx_volume),
        ]

        mute_lbl = "MUTE ALL: ON" if mgr.muted else "MUTE ALL: OFF"
        buttons = [
            Button(pygame.Rect(cx - 240, 385, 230, 48), "Mute Toggle", display_label=mute_lbl, style="purple"),
            Button(pygame.Rect(cx + 10,  385, 230, 48), "Test Sound", display_label="🎵  TEST SOUND", style="yellow"),
            Button(pygame.Rect(cx - 110, 465, 220, 48), "Back", display_label="◀  BACK", style="navy"),
        ]

        return sliders, buttons

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        try:
            audio_manager.stop_music()
            self._tracker.stop()
        except Exception:
            pass
        pygame.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = HandSignRushApp()
    app.run()


if __name__ == "__main__":
    main()
