"""
audio_manager.py — Dedicated retro arcade audio manager for HandSign Rush.

Handles:
- pygame.mixer initialization with graceful fallback on missing audio devices.
- Preloading all 14 sound effects and looping music tracks once.
- Volume management (master, music, SFX) with independent controls.
- Mute/unmute toggling.
- Rate-limiting / cooldowns for frequently triggered sounds (gestures, spawns, warnings).
- Seamless music looping and smooth fade transitions.
- Persistent audio settings stored in assets/audio_settings.json.
"""

from __future__ import annotations

import json
import os
import time

import pygame


# Default cooldowns in seconds to prevent sound spamming
_COOLDOWNS: dict[str, float] = {
    "gesture_detected": 0.40,
    "target_spawn": 0.35,
    "danger_warning": 0.80,
    "low_health": 1.50,
    "button_hover": 0.08,
    "button_click": 0.06,
    "camera_ready": 0.50,
    "camera_error": 0.50,
}

_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "assets", "audio_settings.json")


class AudioManager:
    """Central singleton manager for all game sound effects and background music."""

    _instance: AudioManager | None = None

    def __init__(self) -> None:
        self.available: bool = False
        self.muted: bool = False
        self.master_volume: float = 0.8
        self.music_volume: float = 0.7
        self.sfx_volume: float = 0.85

        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._last_played: dict[str, float] = {}
        self._current_music_name: str | None = None
        self._audio_dir = os.path.join(os.path.dirname(__file__), "assets", "audio")

        # Load stored user preferences
        self.load_settings()

    @classmethod
    def get(cls) -> AudioManager:
        if cls._instance is None:
            cls._instance = AudioManager()
        return cls._instance

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initialize pygame.mixer safely and preload all audio assets."""
        if self.available:
            return True

        try:
            # Low latency configuration (44100Hz, 16-bit, stereo, 512 sample buffer)
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(16)
            self.available = True
        except Exception as e:
            print(f"[AudioManager] Audio device init failed: {e}. Audio disabled.")
            self.available = False
            return False

        self._preload_sounds()
        self._apply_volumes()
        return True

    def _preload_sounds(self) -> None:
        """Preload all sound effect WAVs into memory once."""
        sfx_dir = os.path.join(self._audio_dir, "sfx")
        if not os.path.exists(sfx_dir):
            return

        for filename in os.listdir(sfx_dir):
            if filename.endswith(".wav") or filename.endswith(".ogg"):
                name = os.path.splitext(filename)[0]
                filepath = os.path.join(sfx_dir, filename)
                try:
                    snd = pygame.mixer.Sound(filepath)
                    self._sounds[name] = snd
                except Exception as e:
                    print(f"[AudioManager] Could not preload sound '{filename}': {e}")

    # ------------------------------------------------------------------
    # SFX Playback
    # ------------------------------------------------------------------

    def play_sfx(self, name: str, volume_mult: float = 1.0) -> None:
        """
        Play a sound effect with rate limiting, master/SFX volume scaling,
        and mute checking. Non-blocking.
        """
        if not self.available or self.muted:
            return

        sound = self._sounds.get(name)
        if sound is None:
            return

        # Check rate-limiting cooldown
        now = time.monotonic()
        cooldown = _COOLDOWNS.get(name, 0.02)
        last = self._last_played.get(name, 0.0)
        if now - last < cooldown:
            return
        self._last_played[name] = now

        eff_vol = max(0.0, min(1.0, self.master_volume * self.sfx_volume * volume_mult))
        if eff_vol <= 0.0:
            return

        try:
            sound.set_volume(eff_vol)
            sound.play()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Music Playback
    # ------------------------------------------------------------------

    def play_music(self, name: str, loop: bool = True, fade_ms: int = 400) -> None:
        """
        Play or transition to a background music track smoothly.
        Avoids restarting if the requested track is already playing.
        """
        if not self.available:
            return

        # Track filename candidates
        target_path: str | None = None
        for ext in [".ogg", ".wav", ".mp3"]:
            p = os.path.join(self._audio_dir, "music", f"{name}{ext}")
            if os.path.exists(p):
                target_path = p
                break

        if target_path is None:
            return

        # Don't restart if already playing this track
        if self._current_music_name == name and pygame.mixer.music.get_busy():
            return

        try:
            if pygame.mixer.music.get_busy() and fade_ms > 0:
                pygame.mixer.music.fadeout(fade_ms)

            pygame.mixer.music.load(target_path)
            self._current_music_name = name
            self._apply_volumes()
            loops = -1 if loop else 0
            if fade_ms > 0:
                pygame.mixer.music.play(loops=loops, fade_ms=fade_ms)
            else:
                pygame.mixer.music.play(loops=loops)
        except Exception as e:
            print(f"[AudioManager] Music playback error for '{name}': {e}")

    def stop_music(self, fade_ms: int = 300) -> None:
        """Fade out and stop background music."""
        if not self.available:
            return
        try:
            if fade_ms > 0 and pygame.mixer.music.get_busy():
                pygame.mixer.music.fadeout(fade_ms)
            else:
                pygame.mixer.music.stop()
            self._current_music_name = None
        except Exception:
            pass

    def pause_music(self) -> None:
        if self.available:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass

    def unpause_music(self) -> None:
        if self.available and not self.muted:
            try:
                pygame.mixer.music.unpause()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Volume & Mute Controls
    # ------------------------------------------------------------------

    def set_master_volume(self, value: float) -> None:
        self.master_volume = max(0.0, min(1.0, value))
        self._apply_volumes()
        self.save_settings()

    def set_music_volume(self, value: float) -> None:
        self.music_volume = max(0.0, min(1.0, value))
        self._apply_volumes()
        self.save_settings()

    def set_sfx_volume(self, value: float) -> None:
        self.sfx_volume = max(0.0, min(1.0, value))
        self.save_settings()

    def toggle_mute(self) -> bool:
        """Toggle audio mute state. Returns True if now muted, False if unmuted."""
        self.muted = not self.muted
        self._apply_volumes()
        self.save_settings()
        return self.muted

    def _apply_volumes(self) -> None:
        if not self.available:
            return
        try:
            if self.muted:
                pygame.mixer.music.set_volume(0.0)
            else:
                pygame.mixer.music.set_volume(self.master_volume * self.music_volume)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Settings Persistence
    # ------------------------------------------------------------------

    def save_settings(self) -> None:
        data = {
            "master_volume": round(self.master_volume, 2),
            "music_volume": round(self.music_volume, 2),
            "sfx_volume": round(self.sfx_volume, 2),
            "muted": self.muted,
        }
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_settings(self) -> None:
        if not os.path.exists(_SETTINGS_FILE):
            return
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.master_volume = float(data.get("master_volume", 0.8))
                self.music_volume = float(data.get("music_volume", 0.7))
                self.sfx_volume = float(data.get("sfx_volume", 0.85))
                self.muted = bool(data.get("muted", False))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def initialize_audio() -> bool:
    return AudioManager.get().initialize()


def play_sfx(name: str, volume_mult: float = 1.0) -> None:
    AudioManager.get().play_sfx(name, volume_mult=volume_mult)


def play_music(name: str, loop: bool = True, fade_ms: int = 400) -> None:
    AudioManager.get().play_music(name, loop=loop, fade_ms=fade_ms)


def stop_music(fade_ms: int = 300) -> None:
    AudioManager.get().stop_music(fade_ms=fade_ms)


def set_master_volume(value: float) -> None:
    AudioManager.get().set_master_volume(value)


def set_music_volume(value: float) -> None:
    AudioManager.get().set_music_volume(value)


def set_sfx_volume(value: float) -> None:
    AudioManager.get().set_sfx_volume(value)


def toggle_mute() -> bool:
    return AudioManager.get().toggle_mute()


def get_audio_manager() -> AudioManager:
    return AudioManager.get()
