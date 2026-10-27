"""
gesture_recognition.py — Rule-based hand gesture classifier.

Uses MediaPipe hand landmark indices to determine which fingers are extended,
then maps extension patterns to one of 6 supported gestures.

No ML model files are required — purely geometric/heuristic rules.
Works correctly regardless of horizontal flip applied to the preview image,
because landmark coordinates are extracted before any flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from settings import (
    CONFIDENCE_THRESHOLD,
    FINGER_THRESHOLD,
    GESTURE_NAMES,
    THUMB_THRESHOLD,
)

# ---------------------------------------------------------------------------
# MediaPipe landmark index constants
# ---------------------------------------------------------------------------
WRIST = 0

THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP  = 3
THUMB_TIP = 4

INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8

MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12

RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16

PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20


# ---------------------------------------------------------------------------
# Landmark protocol (duck-typed to work with mediapipe.framework.formats.landmark)
# ---------------------------------------------------------------------------
class _LandmarkLike(Protocol):
    x: float
    y: float
    z: float


@dataclass
class ExtensionState:
    """Which fingers are currently extended."""
    thumb: bool = False
    index: bool = False
    middle: bool = False
    ring: bool = False
    pinky: bool = False

    def count_extended(self) -> int:
        return sum([self.thumb, self.index, self.middle, self.ring, self.pinky])

    def four_fingers_extended(self) -> bool:
        return self.index and self.middle and self.ring and self.pinky

    def four_fingers_closed(self) -> bool:
        return not (self.index or self.middle or self.ring or self.pinky)


class GestureClassifier:
    """
    Stateless hand gesture classifier.

    classify() is pure: identical inputs → identical outputs.
    """

    def classify(
        self,
        landmarks: list[_LandmarkLike],
        handedness: str = "Right",
    ) -> tuple[str | None, float]:
        """
        Classify a set of 21 MediaPipe hand landmarks.

        Parameters
        ----------
        landmarks:
            List of 21 NormalizedLandmark objects with .x, .y attributes
            in [0, 1] normalised image coordinates.
        handedness:
            "Left" or "Right" as reported by MediaPipe (before any image flip).
            The classifier corrects internally for mirrored webcam setups.

        Returns
        -------
        (gesture_name, confidence) where gesture_name is one of GESTURE_NAMES
        or None if no gesture is recognised. confidence ∈ [0.0, 1.0].
        """
        if not landmarks or len(landmarks) != 21:
            return None, 0.0

        ext = self._compute_extension(landmarks, handedness)
        return self._match_gesture(landmarks, ext, handedness)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_extension(
        self,
        lm: list[_LandmarkLike],
        handedness: str,
    ) -> ExtensionState:
        """Determine which fingers are extended using landmark geometry."""
        ext = ExtensionState()

        # ----- Thumb -----
        # Thumb extends laterally; direction depends on which hand.
        # MediaPipe labels the hand from the *unflipped* image perspective.
        # For a right hand (as seen by the camera), the thumb points left (lower x)
        # when extended. For a left hand it points right (higher x).
        # We compare thumb tip vs thumb IP x-coordinate with a threshold.
        tip = lm[THUMB_TIP]
        ip  = lm[THUMB_IP]
        mcp = lm[THUMB_MCP]

        # Also check thumb tip is clearly separated from palm vertically
        # to distinguish thumbs-up from open palm.
        # For thumbs up/down, the thumb extends vertically (up or down) rather than laterally.
        thumb_vertically_extended = (
            (mcp.y - tip.y) > 0.04 or  # pointing up (thumbs up)
            (tip.y - mcp.y) > 0.04     # pointing down (thumbs down)
        )
        if handedness == "Right":
            # Camera sees a right hand — thumb extends to the left in image
            thumb_laterally_extended = (ip.x - tip.x) > THUMB_THRESHOLD
        else:
            # Left hand — thumb extends to the right in image
            thumb_laterally_extended = (tip.x - ip.x) > THUMB_THRESHOLD

        ext.thumb = thumb_laterally_extended or thumb_vertically_extended

        # Sanity: if thumb tip is very close to index/middle MCP the thumb is tucked
        middle_mcp = lm[MIDDLE_MCP]
        index_mcp = lm[INDEX_MCP]
        d_mid = ((tip.x - middle_mcp.x)**2 + (tip.y - middle_mcp.y)**2)**0.5
        d_idx = ((tip.x - index_mcp.x)**2 + (tip.y - index_mcp.y)**2)**0.5
        if d_mid < 0.05 and d_idx < 0.05:
            ext.thumb = False

        # ----- Index -----
        ext.index = _finger_extended(lm, INDEX_TIP, INDEX_PIP, INDEX_MCP)

        # ----- Middle -----
        ext.middle = _finger_extended(lm, MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP)

        # ----- Ring -----
        ext.ring = _finger_extended(lm, RING_TIP, RING_PIP, RING_MCP)

        # ----- Pinky -----
        ext.pinky = _finger_extended(lm, PINKY_TIP, PINKY_PIP, PINKY_MCP)

        return ext

    def _match_gesture(
        self,
        lm: list[_LandmarkLike],
        ext: ExtensionState,
        handedness: str,
    ) -> tuple[str | None, float]:
        """
        Map an ExtensionState to a named gesture.
        Returns (name, confidence) or (None, 0.0).
        """
        # When 4 fingers are closed:
        if ext.four_fingers_closed():
            # In a true thumbs-up, thumb tip is noticeably higher (smaller y) than index MCP
            # and thumb is pointing upwards from IP.
            # In a fist, thumb tip rests near index/middle MCP level.
            thumb_elevated = (lm[INDEX_MCP].y - lm[THUMB_TIP].y) > 0.045
            thumb_pointing_up = (lm[THUMB_IP].y - lm[THUMB_TIP].y) > 0.02 and (lm[THUMB_MCP].y - lm[THUMB_TIP].y) > 0.05

            if thumb_elevated and thumb_pointing_up:
                conf_up = self._thumb_up_confidence(lm, handedness)
                if conf_up >= CONFIDENCE_THRESHOLD:
                    return "thumbs_up", conf_up

            # Check thumbs-down (thumb pointing downward below index MCP and wrist)
            thumb_depressed = (lm[THUMB_TIP].y - lm[INDEX_MCP].y) > 0.045
            thumb_pointing_down = (lm[THUMB_TIP].y - lm[THUMB_IP].y) > 0.02 and (lm[THUMB_TIP].y - lm[THUMB_MCP].y) > 0.05
            if thumb_depressed and thumb_pointing_down:
                conf_down = self._thumb_down_confidence(lm, handedness)
                if conf_down >= CONFIDENCE_THRESHOLD:
                    return "thumbs_down", conf_down

            # If not thumbs-up or down, check closed fist
            conf_fist = self._fist_confidence(lm, ext)
            if conf_fist >= 0.65:
                return "closed_fist", conf_fist

        # ---- open_palm: all 5 extended ----
        if ext.thumb and ext.four_fingers_extended():
            conf = self._palm_confidence(lm, ext)
            if conf >= CONFIDENCE_THRESHOLD:
                return "open_palm", conf

        # ---- peace_sign: index + middle extended, others closed ----
        if ext.index and ext.middle and not ext.ring and not ext.pinky:
            conf = self._peace_confidence(lm, ext)
            if conf >= CONFIDENCE_THRESHOLD:
                return "peace_sign", conf

        # ---- index_up: only index extended ----
        if ext.index and not ext.middle and not ext.ring and not ext.pinky:
            conf = self._index_up_confidence(lm, ext)
            if conf >= CONFIDENCE_THRESHOLD:
                return "index_up", conf

        return None, 0.0

    # ------------------------------------------------------------------
    # Per-gesture confidence scorers
    # ------------------------------------------------------------------

    def _fist_confidence(self, lm: list[_LandmarkLike], ext: ExtensionState) -> float:
        """Confidence that all fingers are tightly curled."""
        # For each finger, when curled, TIP is closer to wrist than PIP (or PIP distance to wrist is greater than TIP distance)
        # Also check fingertips are close to palm (MCP joints)
        scores: list[float] = []
        wrist = lm[WRIST]
        for tip_i, pip_i, mcp_i in [
            (INDEX_TIP, INDEX_PIP, INDEX_MCP),
            (MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP),
            (RING_TIP, RING_PIP, RING_MCP),
            (PINKY_TIP, PINKY_PIP, PINKY_MCP),
        ]:
            d_tip_wrist = ((lm[tip_i].x - wrist.x)**2 + (lm[tip_i].y - wrist.y)**2)**0.5
            d_pip_wrist = ((lm[pip_i].x - wrist.x)**2 + (lm[pip_i].y - wrist.y)**2)**0.5
            # TIP closer to wrist than PIP indicates curled finger
            curled_score = 1.0 if d_tip_wrist < d_pip_wrist + 0.02 else max(0.0, 1.0 - (d_tip_wrist - d_pip_wrist) / 0.05)
            scores.append(curled_score)

        # Thumb curled: thumb tip closer to middle/index MCP than when extended
        d_thumb_idx = ((lm[THUMB_TIP].x - lm[INDEX_MCP].x)**2 + (lm[THUMB_TIP].y - lm[INDEX_MCP].y)**2)**0.5
        thumb_score = min(1.0, max(0.0, (0.16 - d_thumb_idx) / 0.08))
        scores.append(thumb_score)

        return sum(scores) / len(scores)

    def _palm_confidence(self, lm: list[_LandmarkLike], ext: ExtensionState) -> float:
        """Confidence that hand is fully open."""
        # All 5 fingers must be extended; tips spread out
        count = ext.count_extended()
        base_score = count / 5.0
        # Bonus: spread between leftmost and rightmost fingertip
        tips = [lm[INDEX_TIP], lm[MIDDLE_TIP], lm[RING_TIP], lm[PINKY_TIP]]
        xs = [t.x for t in tips]
        spread = max(xs) - min(xs)
        spread_score = min(1.0, spread / 0.25)
        return 0.7 * base_score + 0.3 * spread_score

    def _thumb_up_confidence(self, lm: list[_LandmarkLike], handedness: str) -> float:
        """Confidence for thumbs-up: thumb tip above both index MCP and thumb IP."""
        thumb_tip = lm[THUMB_TIP]
        thumb_ip = lm[THUMB_IP]
        thumb_mcp = lm[THUMB_MCP]
        index_mcp = lm[INDEX_MCP]
        # In image coordinates, y is 0 at top and 1 at bottom.
        # Thumb pointing up means tip is above IP, MCP, and index MCP.
        is_up = (thumb_ip.y - thumb_tip.y) > 0.015 and (thumb_mcp.y - thumb_tip.y) > 0.03
        if not is_up:
            return 0.0
        margin = max(index_mcp.y - thumb_tip.y, thumb_mcp.y - thumb_tip.y)
        return min(1.0, max(0.5, margin / 0.06 + 0.5))

    def _thumb_down_confidence(self, lm: list[_LandmarkLike], handedness: str) -> float:
        """Confidence for thumbs-down: thumb tip pointing downward below thumb IP and wrist/MCP."""
        thumb_tip = lm[THUMB_TIP]
        thumb_ip = lm[THUMB_IP]
        thumb_mcp = lm[THUMB_MCP]
        wrist = lm[WRIST]
        index_mcp = lm[INDEX_MCP]
        # Thumb pointing down means tip is below IP and below index MCP/wrist
        is_down = (thumb_tip.y - thumb_ip.y) > 0.015 and (thumb_tip.y - thumb_mcp.y) > 0.03
        if not is_down:
            return 0.0
        margin = max(thumb_tip.y - index_mcp.y, thumb_tip.y - wrist.y)
        return min(1.0, max(0.5, margin / 0.06 + 0.5))

    def _peace_confidence(self, lm: list[_LandmarkLike], ext: ExtensionState) -> float:
        """Confidence for peace/V sign: index + middle up, others down."""
        correct_extended = int(ext.index) + int(ext.middle)
        correct_closed = int(not ext.ring) + int(not ext.pinky)
        # Thumb should be closed or tucked
        thumb_closed = int(not ext.thumb)
        total = correct_extended + correct_closed + thumb_closed
        return total / 5.0

    def _index_up_confidence(self, lm: list[_LandmarkLike], ext: ExtensionState) -> float:
        """Confidence for index-only pointing up."""
        correct = int(ext.index) + int(not ext.middle) + int(not ext.ring) + int(not ext.pinky) + int(not ext.thumb)
        return correct / 5.0


# ---------------------------------------------------------------------------
# Module-level utility
# ---------------------------------------------------------------------------

def _finger_extended(
    lm: list[_LandmarkLike],
    tip_i: int,
    pip_i: int,
    mcp_i: int,
) -> bool:
    """
    Return True when the finger's tip is extended.
    Checks that TIP is vertically above PIP (in standard upright orientation)
    AND tip distance from wrist is noticeably greater than PIP distance from wrist.
    """
    tip = lm[tip_i]
    pip = lm[pip_i]
    mcp = lm[mcp_i]
    wrist = lm[WRIST]

    # Vertical extension check
    vertically_extended = (pip.y - tip.y) > FINGER_THRESHOLD

    # Radial distance from wrist check (orientation-independent)
    d_tip_wrist = ((tip.x - wrist.x)**2 + (tip.y - wrist.y)**2)**0.5
    d_pip_wrist = ((pip.x - wrist.x)**2 + (pip.y - wrist.y)**2)**0.5
    radially_extended = d_tip_wrist > (d_pip_wrist + 0.035)

    return vertically_extended and radially_extended
