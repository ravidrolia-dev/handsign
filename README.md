# HandSign Rush

A webcam-controlled survival arcade game. Destroy falling hand-sign targets by
performing the matching gesture in front of your camera. Speed increases with
your score. Survive as long as you can!

---

## Requirements

- **Python 3.14.3** (or 3.11–3.14 should all work)
- A working webcam
- The packages listed in `requirements.txt`

---

## Installation

```bash
# 1. Clone / download the project
cd handsign-rush

# 2. Create a virtual environment (recommended)
py -3.11 -m venv .venv # OR python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.\.venv\Scripts\Activate.ps1       # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the Game

```bash
cd handsign_rush
python main.py
```

### Mock camera mode (no webcam required)

If you do not have a webcam, enable mock mode in `settings.py`:

```python
MOCK_CAMERA: bool = True
```

The game will cycle through gesture names automatically — useful for testing
or CI environments.

---

## Controls

| Key / Action | Effect |
|---|---|
| Mouse click | Navigate menus, click buttons |
| **Esc** | Pause during play · Back from sub-screens |
| **Enter** | Confirm camera check and proceed |
| Close window | Quit cleanly |

---

## Gameplay

1. **Main Menu** → click **Play**.
2. **Camera Check** — verify your webcam is detected. Click **Continue** or press **Enter**.
3. **Countdown** 3 → 2 → 1 → GO!
4. **Survive** — two target lanes fall from the top. Reproduce the gesture shown on a target to destroy it.
5. Missing a target (it crosses the red danger line) costs **one life**. You start with **3**.
6. Score and speed increase over time. The game ends when all lives are lost.

### Scoring

| Event | Points |
|---|---|
| Target destroyed | 10 |
| Combo bonus | +10 × combo × 0.5 per extra hit |

---

## Hand Gestures

| Gesture | How to perform |
|---|---|
| **Open Palm** | Spread all five fingers open |
| **Closed Fist** | Curl all fingers into a fist |
| **Thumbs Up** | Fist with thumb pointing upward |
| **Thumbs Down** | Fist with thumb pointing downward |
| **Peace Sign** | Index and middle finger raised, others curled |
| **Index Up** | Only index finger raised (pointing up) |

**Tips:**
- Hold the gesture steadily for ~0.4 s — it fires automatically.
- Keep your hand clearly in frame and well-lit.
- A cooldown of ~0.6 s after each match prevents one held pose from clearing multiple targets.

---

## Camera Troubleshooting

### "Cannot open camera"
- Ensure no other application (Zoom, Skype, browser) is using the camera.
- Try changing `CAMERA_INDEX` in `settings.py` from `0` to `1` or `2`.
- On Linux, check permissions: `ls -l /dev/video*` and add yourself to the `video` group.

### "Camera opened but no frames received"
- Increase `CAMERA_TIMEOUT` in `settings.py`.
- Unplug and replug the camera; restart the game.

### Poor gesture detection
- Ensure your hand is well-lit and fully visible.
- Keep your hand roughly 30–70 cm from the camera.
- Avoid very fast hand movements between gestures.
- Adjust `CONFIDENCE_THRESHOLD`, `FINGER_THRESHOLD`, or `STABILITY_DURATION` in `settings.py` to tune sensitivity.

### macOS permissions
- Go to **System Settings → Privacy & Security → Camera** and allow Terminal (or your IDE) access.

### Windows permissions
- Go to **Settings → Privacy → Camera** and ensure apps can access the camera.

---

## Architecture

```
handsign_rush/
├── main.py               # Entry point, state machine, app lifecycle
├── game.py               # Game state, spawning, scoring, gesture matching
├── settings.py           # All configurable constants
├── gesture_recognition.py # Rule-based gesture classifier (no model files)
├── hand_tracker.py       # Background thread: OpenCV + MediaPipe capture
├── target.py             # FallingTarget objects and animations
└── ui.py                 # All Pygame rendering (menus, HUD, effects)
```

The webcam runs in a **daemon background thread** — it never blocks the 60 fps Pygame loop.

---

## Tuning & Configuration

All game parameters live in `settings.py`:

| Constant | Default | Effect |
|---|---|---|
| `INITIAL_FALL_SPEED` | 80 px/s | Starting target fall speed |
| `MAX_FALL_SPEED` | 280 px/s | Speed ceiling |
| `SPEED_SCALE_FACTOR` | 0.4 | Speed growth per point |
| `INITIAL_SPAWN_INTERVAL` | 3.5 s | Starting spawn gap |
| `MIN_SPAWN_INTERVAL` | 1.2 s | Spawn interval floor |
| `STABILITY_DURATION` | 0.4 s | Hold time before gesture fires |
| `GESTURE_COOLDOWN` | 0.6 s | Cooldown after each match |
| `CONFIDENCE_THRESHOLD` | 0.75 | Minimum classification confidence |
| `MOCK_CAMERA` | False | Enable simulated gestures |

---

## License

MIT — free to use, modify, and distribute.
