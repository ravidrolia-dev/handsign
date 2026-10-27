"""
settings.py — Central configuration for HandSign Rush.
All tunable constants live here; no logic, no imports beyond stdlib typing.
"""

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
WINDOW_W: int = 1280
WINDOW_H: int = 720
FULLSCREEN: bool = True
FPS: int = 60
WINDOW_TITLE: str = "HandSign Rush"

# ---------------------------------------------------------------------------
# Lanes  (two vertical lanes for falling targets)
# ---------------------------------------------------------------------------
LANE_COUNT: int = 2
# Targets are centred in these x positions (computed relative to window width)
LANE_X: list[int] = [320, 960]  # left lane, right lane

# ---------------------------------------------------------------------------
# Gameplay
# ---------------------------------------------------------------------------
INITIAL_LIVES: int = 3
POINTS_PER_TARGET: int = 10
COMBO_MULTIPLIER: float = 0.5   # bonus = base * combo * multiplier

# Falling speed (pixels/second)
INITIAL_FALL_SPEED: float = 80.0
MAX_FALL_SPEED: float = 280.0
SPEED_SCALE_FACTOR: float = 0.4  # speed += score * factor

# Spawn interval (seconds between spawning a new target)
INITIAL_SPAWN_INTERVAL: float = 3.5
MIN_SPAWN_INTERVAL: float = 1.2
SPAWN_SCALE_FACTOR: float = 0.015  # interval -= score * factor

# Max simultaneous targets on screen
MAX_ACTIVE_TARGETS: int = 4

# Danger line position (fraction of window height)
DANGER_Y_FRACTION: float = 0.87

# Target visual size
TARGET_SIZE: int = 90  # bounding box width/height in pixels

# ---------------------------------------------------------------------------
# Dual-Hand Gameplay Settings (HandSign Rush 2.0)
# ---------------------------------------------------------------------------
SYNC_WINDOW_SEC: float = 0.30       # Max time difference between left & right hand matches (300ms)
PERFECT_SYNC_WINDOW_SEC: float = 0.12  # Bonus points if matched within 120ms
PERFECT_SYNC_BONUS: int = 25        # Extra points for tight synchronization

# Dual zone positions (X centers for left and right targets)
LEFT_TARGET_X: int = 340
RIGHT_TARGET_X: int = 940

# Horizontal SHM Oscillation for falling targets
TARGET_SHM_AMPLITUDE: float = 65.0   # Horizontal sway radius in pixels (A)
TARGET_SHM_OMEGA: float = 2.4        # Angular frequency in rad/s (omega)

# Gesture recognition
# ---------------------------------------------------------------------------
# Seconds a gesture must be held before it is recognized as stable
STABILITY_DURATION: float = 0.15     # Reduced from 0.4 for responsive dual-hand feel
# Seconds cooldown after a pair cancellation before the next match can complete
PAIR_COOLDOWN: float = 0.4
# Minimum mediapipe confidence required
CONFIDENCE_THRESHOLD: float = 0.70
# Landmark distance threshold for finger extension (normalised coords)
FINGER_THRESHOLD: float = 0.035
THUMB_THRESHOLD: float = 0.04

# ---------------------------------------------------------------------------
# Webcam preview
# ---------------------------------------------------------------------------
CAM_PREVIEW_W: int = 240
CAM_PREVIEW_H: int = 180
CAM_PREVIEW_MARGIN: int = 12
# Device index for OpenCV VideoCapture
CAMERA_INDEX: int = 0
# Seconds to wait for first camera frame before reporting failure
CAMERA_TIMEOUT: float = 5.0

# ---------------------------------------------------------------------------
# Countdown
# ---------------------------------------------------------------------------
COUNTDOWN_START: int = 3
COUNTDOWN_STEP_DURATION: float = 0.9  # seconds per digit

# ---------------------------------------------------------------------------
# Particles
# ---------------------------------------------------------------------------
MAX_PARTICLES: int = 120
PARTICLE_LIFETIME: float = 0.8   # seconds
PARTICLE_SPEED: float = 180.0    # pixels/second (initial)
PARTICLE_COUNT_PER_DESTROY: int = 16

# ---------------------------------------------------------------------------
# Colours  (R, G, B)
# ---------------------------------------------------------------------------
BG_COLOR: tuple[int, int, int] = (10, 8, 30)
BG_COLOR_TOP: tuple[int, int, int] = (12, 10, 40)
BG_COLOR_BOTTOM: tuple[int, int, int] = (6, 4, 18)

NEON_CYAN: tuple[int, int, int] = (0, 240, 255)
NEON_VIOLET: tuple[int, int, int] = (160, 32, 240)
NEON_PINK: tuple[int, int, int] = (255, 64, 160)
NEON_GREEN: tuple[int, int, int] = (80, 255, 120)
NEON_YELLOW: tuple[int, int, int] = (255, 220, 0)

DANGER_COLOR: tuple[int, int, int] = (255, 48, 48)
TEXT_WHITE: tuple[int, int, int] = (230, 230, 240)
TEXT_DIM: tuple[int, int, int] = (120, 120, 140)
BUTTON_NORMAL: tuple[int, int, int] = (30, 25, 70)
BUTTON_HOVER: tuple[int, int, int] = (60, 40, 120)
BUTTON_BORDER: tuple[int, int, int] = (80, 60, 180)

# Per-gesture colours for target icons
GESTURE_COLORS: dict[str, tuple[int, int, int]] = {
    "open_palm":    (0, 240, 255),    # cyan
    "closed_fist":  (160, 32, 240),   # violet
    "thumbs_up":    (80, 255, 120),   # green
    "thumbs_down":  (255, 64, 160),   # pink
    "peace_sign":   (255, 220, 0),    # yellow
    "index_up":     (255, 140, 0),    # orange
}

# ---------------------------------------------------------------------------
# Gestures
# ---------------------------------------------------------------------------
GESTURE_NAMES: list[str] = [
    "open_palm",
    "closed_fist",
    "thumbs_up",
    "thumbs_down",
    "peace_sign",
    "index_up",
]

GESTURE_LABELS: dict[str, str] = {
    "open_palm":    "Open Palm",
    "closed_fist":  "Closed Fist",
    "thumbs_up":    "Thumbs Up",
    "thumbs_down":  "Thumbs Down",
    "peace_sign":   "Peace Sign",
    "index_up":     "Index Up",
}

GESTURE_EMOJIS: dict[str, str] = {
    "open_palm":    "✋",
    "closed_fist":  "✊",
    "thumbs_up":    "👍",
    "thumbs_down":  "👎",
    "peace_sign":   "✌",
    "index_up":     "☝",
}

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# Background thread stop timeout (seconds)
STOP_TIMEOUT: float = 2.0
# Enable mock camera mode (cycles gestures without real webcam)
MOCK_CAMERA: bool = False
MOCK_GESTURE_INTERVAL: float = 1.5  # seconds per mock gesture cycle

# High score save file
HIGHSCORE_FILE: str = "highscore.json"
