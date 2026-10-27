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
class GestureFrame:
    """Snapshot of gesture state at a point in time."""
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
        """Return a shallow copy of the current frame — non-blocking."""
        with self._lock:
            # dataclass copy (shallow — np.ndarray not deep-copied, just ref)
            return GestureFrame(
                gesture=self._frame.gesture,
                confidence=self._frame.confidence,
                landmarks_2d=self._frame.landmarks_2d,
                preview_frame=self._frame.preview_frame,
                timestamp=self._frame.timestamp,
                camera_ok=self._frame.camera_ok,
                error_msg=self._frame.error_msg,
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

            gesture = GESTURE_NAMES[self._gesture_idx]

            # Build a simple placeholder preview frame
            preview = np.zeros((CAM_PREVIEW_H, CAM_PREVIEW_W, 3), dtype=np.uint8)
            preview[:] = (20, 20, 50)
            cv2.putText(
                preview,
                f"MOCK: {gesture}",
                (10, CAM_PREVIEW_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 240, 255),
                1,
                cv2.LINE_AA,
            )

            frame = GestureFrame(
                gesture=gesture,
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

            # Initialise MediaPipe Hands
            hands = mp_hands_module.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.4,
                min_tracking_confidence=0.4,
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
                # so that left/right handedness is correct.
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                results = hands.process(frame_rgb)

                gesture: str | None = None
                confidence: float = 0.0
                landmarks_2d: list[tuple[int, int]] | None = None

                if results.multi_hand_landmarks and results.multi_handedness:
                    hand_lm = results.multi_hand_landmarks[0]
                    hand_info = results.multi_handedness[0]
                    handedness_label = hand_info.classification[0].label  # "Left" or "Right"

                    # Classify on raw landmarks
                    gesture, confidence = self._classifier.classify(
                        hand_lm.landmark, handedness_label
                    )

                    # Convert landmarks to pixel coords for the PREVIEW (flipped) image
                    h_orig, w_orig = frame_bgr.shape[:2]
                    # Preview dimensions after resize
                    pw, ph = CAM_PREVIEW_W, CAM_PREVIEW_H
                    sx = pw / w_orig
                    sy = ph / h_orig
                    landmarks_2d = []
                    for lm in hand_lm.landmark:
                        # Mirror x for the flipped preview
                        px = int((1.0 - lm.x) * w_orig * sx)
                        py = int(lm.y * h_orig * sy)
                        landmarks_2d.append((px, py))

                # Flip for natural mirror preview AFTER landmark extraction
                preview = cv2.flip(frame_bgr, 1)
                preview = cv2.resize(preview, (CAM_PREVIEW_W, CAM_PREVIEW_H))

                self._shared.write(
                    GestureFrame(
                        gesture=gesture,
                        confidence=confidence,
                        landmarks_2d=landmarks_2d,
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
