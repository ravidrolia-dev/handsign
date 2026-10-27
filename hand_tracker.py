"""
hand_tracker.py — Background webcam capture and MediaPipe integration.

HandTracker runs OpenCV + MediaPipe in a daemon thread so it never blocks
the Pygame main loop.  Results are written to a SharedGestureState that the
main thread reads without holding the lock for long.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field

import cv2
import mediapipe as mp
import numpy as np

from gesture_recognition import GestureClassifier
from settings import (
    CAMERA_INDEX,
    CAMERA_TIMEOUT,
    CAM_PREVIEW_H,
    CAM_PREVIEW_W,
    GESTURE_NAMES,
    MOCK_CAMERA,
    MOCK_GESTURE_INTERVAL,
    STOP_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Shared data structure (main thread reads, background thread writes)
# ---------------------------------------------------------------------------

@dataclass
class HandData:
    """Tracking and gesture data for a single hand."""
    detected: bool = False
    gesture: str | None = None
    confidence: float = 0.0
    landmarks_2d: list[tuple[int, int]] | None = None  # pixel coords on preview (flipped)
    raw_handedness: str = ""                           # MediaPipe raw label ("Left" or "Right")


@dataclass
class GestureFrame:
    """Snapshot of dual-hand gesture state at a point in time."""
    # Dual-hand independent data
    left_hand: HandData = field(default_factory=HandData)
    right_hand: HandData = field(default_factory=HandData)

    # Legacy/convenience single-hand fields (backwards compatibility)
    gesture: str | None = None
    confidence: float = 0.0
    landmarks_2d: list[tuple[int, int]] | None = None  # pixel coords on preview

    preview_frame: np.ndarray | None = None            # BGR, preview-sized
    timestamp: float = field(default_factory=time.monotonic)
    camera_ok: bool = False
    error_msg: str | None = None


class SharedGestureState:
    """
    Thread-safe container for the most recent GestureFrame.
    The background thread writes; the main thread reads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame = GestureFrame()

    def write(self, frame: GestureFrame) -> None:
        with self._lock:
            self._frame = frame

    def read(self) -> GestureFrame:
        """Return a copy of the current frame — non-blocking."""
        with self._lock:
            f = self._frame
            # Deep-copy hand data so threads don't race
            lh = HandData(
                detected=f.left_hand.detected,
                gesture=f.left_hand.gesture,
                confidence=f.left_hand.confidence,
                landmarks_2d=list(f.left_hand.landmarks_2d) if f.left_hand.landmarks_2d else None,
                raw_handedness=f.left_hand.raw_handedness,
            )
            rh = HandData(
                detected=f.right_hand.detected,
                gesture=f.right_hand.gesture,
                confidence=f.right_hand.confidence,
                landmarks_2d=list(f.right_hand.landmarks_2d) if f.right_hand.landmarks_2d else None,
                raw_handedness=f.right_hand.raw_handedness,
            )
            return GestureFrame(
                left_hand=lh,
                right_hand=rh,
                gesture=f.gesture,
                confidence=f.confidence,
                landmarks_2d=list(f.landmarks_2d) if f.landmarks_2d else None,
                preview_frame=f.preview_frame,
                timestamp=f.timestamp,
                camera_ok=f.camera_ok,
                error_msg=f.error_msg,
            )


# ---------------------------------------------------------------------------
# Mock camera (no physical webcam required)
# ---------------------------------------------------------------------------

class _MockCaptureWorker:
    """
    Cycles through all gesture names at a fixed interval.
    Used for testing without a webcam.
    """

    def __init__(self, shared: SharedGestureState) -> None:
        self._shared = shared
        self._running = False
        self._thread: threading.Thread | None = None
        self._gesture_idx = 0
        self._gesture_timer = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mock-tracker")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=STOP_TIMEOUT)

    def is_running(self) -> bool:
        return self._running

    def camera_ok(self) -> bool:
        return True

    def _loop(self) -> None:
        last_time = time.monotonic()
        while self._running:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            self._gesture_timer += dt
            if self._gesture_timer >= MOCK_GESTURE_INTERVAL:
                self._gesture_timer = 0.0
                self._gesture_idx = (self._gesture_idx + 1) % len(GESTURE_NAMES)

            g_left = GESTURE_NAMES[self._gesture_idx]
            g_right = GESTURE_NAMES[(self._gesture_idx + 2) % len(GESTURE_NAMES)]

            # Build a simple placeholder preview frame
            preview = np.zeros((CAM_PREVIEW_H, CAM_PREVIEW_W, 3), dtype=np.uint8)
            preview[:] = (20, 20, 50)
            cv2.putText(
                preview,
                f"L:{g_left[:6]} R:{g_right[:6]}",
                (8, CAM_PREVIEW_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (0, 240, 255),
                1,
                cv2.LINE_AA,
            )

            frame = GestureFrame(
                left_hand=HandData(
                    detected=True,
                    gesture=g_left,
                    confidence=0.95,
                    landmarks_2d=None,
                    raw_handedness="Left",
                ),
                right_hand=HandData(
                    detected=True,
                    gesture=g_right,
                    confidence=0.95,
                    landmarks_2d=None,
                    raw_handedness="Right",
                ),
                gesture=g_left,
                confidence=0.95,
                landmarks_2d=None,
                preview_frame=preview,
                timestamp=now,
                camera_ok=True,
                error_msg=None,
            )
            self._shared.write(frame)
            time.sleep(0.033)  # ~30 fps


# ---------------------------------------------------------------------------
# Real camera worker
# ---------------------------------------------------------------------------

class HandTracker:
    """
    Manages one OpenCV VideoCapture + MediaPipe Hands in a daemon thread.

    Usage:
        shared = SharedGestureState()
        tracker = HandTracker(shared)
        tracker.start()
        ...
        frame = shared.read()  # call from main thread
        ...
        tracker.stop()
    """

    def __init__(self, shared: SharedGestureState, device_index: int = CAMERA_INDEX) -> None:
        self._shared = shared
        self._device_index = device_index
        self._running = False
        self._thread: threading.Thread | None = None
        self._camera_ok = False
        self._classifier = GestureClassifier()

        # Flag set by background thread when camera open fails
        self._error_msg: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background capture thread."""
        if self._thread and self._thread.is_alive():
            return  # already running
        self._running = True
        self._camera_ok = False
        self._error_msg = None
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="hand-tracker",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it to join."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=STOP_TIMEOUT)
            self._thread = None

    def restart(self) -> None:
        """Stop then start again — used when retrying after camera error."""
        self.stop()
        time.sleep(0.3)
        self.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def camera_ok(self) -> bool:
        return self._camera_ok

    def get_error(self) -> str | None:
        return self._error_msg

    # ------------------------------------------------------------------
    # Background thread body
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        mp_hands_module = mp.solutions.hands  # type: ignore[attr-defined]
        cap: cv2.VideoCapture | None = None
        hands = None

        try:
            # Open camera with fallback (especially DirectShow on Windows where MSMF can fail to yield frames)
            backends = []
            if sys.platform.startswith("win"):
                backends.append(cv2.CAP_DSHOW)
            backends.append(cv2.CAP_ANY)

            candidate_indices = [self._device_index]
            for alt_idx in (0, 1):
                if alt_idx not in candidate_indices:
                    candidate_indices.append(alt_idx)

            for cand_idx in candidate_indices:
                for backend in backends:
                    temp_cap = cv2.VideoCapture(cand_idx, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(cand_idx)
                    if not temp_cap.isOpened():
                        temp_cap.release()
                        continue

                    # Verify frames can actually be read and contain visual data (mean > 1.0 to ignore pitch black virtual/disconnected cameras)
                    got_frame = False
                    deadline = time.monotonic() + min(CAMERA_TIMEOUT, 2.5)
                    while time.monotonic() < deadline:
                        ret, test_frame = temp_cap.read()
                        if ret and test_frame is not None and float(np.mean(test_frame)) > 1.0:
                            got_frame = True
                            break
                        time.sleep(0.05)

                    if got_frame:
                        cap = temp_cap
                        self._device_index = cand_idx
                        break
                    else:
                        temp_cap.release()

                if cap is not None:
                    break

            if cap is None or not cap.isOpened():
                self._error_msg = f"Cannot open or read frames from camera (tried index {self._device_index})"
                self._shared.write(GestureFrame(error_msg=self._error_msg))
                return

            self._camera_ok = True

            # Initialise MediaPipe Hands for up to 2 hands
            hands = mp_hands_module.Hands(
                static_image_mode=False,
                max_num_hands=2,
                min_detection_confidence=0.45,
                min_tracking_confidence=0.45,
            )

            while self._running:
                ret, frame_bgr = cap.read()
                if not ret or frame_bgr is None:
                    # Camera disconnected
                    self._camera_ok = False
                    self._error_msg = "Camera disconnected"
                    self._shared.write(
                        GestureFrame(
                            camera_ok=False,
                            error_msg=self._error_msg,
                            timestamp=time.monotonic(),
                        )
                    )
                    # Try to recover
                    time.sleep(0.1)
                    continue

                # Process landmarks on the ORIGINAL (un-flipped) frame
                # MediaPipe Hands raw classification:
                # When camera faces player (selfie mode):
                #   - Player's LEFT hand appears on camera right -> MediaPipe labels as "Right"
                #   - Player's RIGHT hand appears on camera left -> MediaPipe labels as "Left"
                # Therefore:
                #   raw_handedness == "Right" -> Player's LEFT Hand
                #   raw_handedness == "Left"  -> Player's RIGHT Hand
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                results = hands.process(frame_rgb)

                left_hand_data = HandData()
                right_hand_data = HandData()
                all_landmarks_2d: list[tuple[int, int]] = []

                h_orig, w_orig = frame_bgr.shape[:2]
                pw, ph = CAM_PREVIEW_W, CAM_PREVIEW_H
                sx = pw / w_orig
                sy = ph / h_orig

                if results.multi_hand_landmarks and results.multi_handedness:
                    for hand_lm, hand_info in zip(results.multi_hand_landmarks, results.multi_handedness):
                        raw_label = hand_info.classification[0].label  # "Left" or "Right"
                        # Geometric wrist position in camera coordinates (unflipped: x=0 is camera left, x=1 is camera right)
                        wrist_x = hand_lm.landmark[0].x

                        # Classify gesture on raw landmarks passing raw_label to GestureClassifier
                        gesture, confidence = self._classifier.classify(
                            hand_lm.landmark, raw_label
                        )

                        # Convert landmarks to pixel coordinates for the mirrored preview (x mirrored)
                        hand_landmarks_2d = []
                        for lm in hand_lm.landmark:
                            px = int((1.0 - lm.x) * w_orig * sx)
                            py = int(lm.y * h_orig * sy)
                            hand_landmarks_2d.append((px, py))
                            all_landmarks_2d.append((px, py))

                        # Map to user's perspective:
                        # In selfie view, user's left hand has wrist_x > 0.5 (camera right) and raw_label == "Right"
                        # User's right hand has wrist_x < 0.5 (camera left) and raw_label == "Left"
                        # We combine raw_label with spatial position for robust disambiguation
                        is_user_left = (raw_label == "Right")
                        if len(results.multi_hand_landmarks) == 2:
                            # When both hands are present, also cross-check spatial position
                            # (wrist further right in camera = user's left hand)
                            other_wrist_x = [
                                h.landmark[0].x for h in results.multi_hand_landmarks if h != hand_lm
                            ][0]
                            is_user_left = wrist_x > other_wrist_x

                        h_data = HandData(
                            detected=True,
                            gesture=gesture,
                            confidence=confidence,
                            landmarks_2d=hand_landmarks_2d,
                            raw_handedness=raw_label,
                        )

                        if is_user_left:
                            left_hand_data = h_data
                        else:
                            right_hand_data = h_data

                # Flip for natural mirror preview AFTER landmark extraction
                preview = cv2.flip(frame_bgr, 1)
                preview = cv2.resize(preview, (CAM_PREVIEW_W, CAM_PREVIEW_H))

                # Primary gesture for legacy components (prefers left hand then right hand)
                primary_gesture = left_hand_data.gesture or right_hand_data.gesture
                primary_confidence = left_hand_data.confidence if left_hand_data.gesture else right_hand_data.confidence

                self._shared.write(
                    GestureFrame(
                        left_hand=left_hand_data,
                        right_hand=right_hand_data,
                        gesture=primary_gesture,
                        confidence=primary_confidence,
                        landmarks_2d=all_landmarks_2d if all_landmarks_2d else None,
                        preview_frame=preview,
                        timestamp=time.monotonic(),
                        camera_ok=True,
                        error_msg=None,
                    )
                )

        except Exception as exc:  # noqa: BLE001
            self._error_msg = str(exc)
            self._camera_ok = False
            self._shared.write(
                GestureFrame(camera_ok=False, error_msg=self._error_msg)
            )
        finally:
            if hands is not None:
                try:
                    hands.close()
                except Exception:  # noqa: BLE001
                    pass
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Factory — returns real or mock tracker based on settings
# ---------------------------------------------------------------------------

def create_tracker(shared: SharedGestureState) -> HandTracker | _MockCaptureWorker:
    """Return a mock worker if MOCK_CAMERA is True, else a real HandTracker."""
    if MOCK_CAMERA:
        return _MockCaptureWorker(shared)
    return HandTracker(shared)
