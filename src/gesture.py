"""Gesture recognition: enum, debouncer, landmark classifier, and detector.

mediapipe is imported lazily inside `GestureDetector` so the rest of this
module (Gesture, GestureDebouncer, classify_landmarks) can be imported in
test environments without the heavy native dependency.
"""

import enum
import logging
import time
import os

from src.config import Config

# Model Path
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "hand_landmarker.task")

# MediaPipe HandLandmarker indices for finger tips / PIP joints
_FINGERS = {
    "index": (8, 6),
    "middle": (12, 10),
    "ring": (16, 14),
    "pinky": (20, 18),
}

logger = logging.getLogger(__name__)


class Gesture(str, enum.Enum):
    """Recognised gesture intents. Inheriting from str keeps the values
    JSON-serialisable and Queue-friendly across processes."""

    START_RECORDING = "START_RECORDING"
    STOP_RECORDING = "STOP_RECORDING"


class GestureDebouncer:
    """
    Confirms a gesture only after the user holds it for
    Config.GESTURE_CONFIRMATION_SECONDS continuously, and fires the
    associated action exactly once per hold.

    The debouncer is intentionally a plain class with explicit fields so it
    can be unit-tested without spinning up the camera pipeline.
    """

    def __init__(self, on_start, on_stop, clock=time.monotonic):
        self._on_start = on_start
        self._on_stop = on_stop
        self._clock = clock
        self._pending = None
        self._pending_since = 0.0
        self._last_confirmed = None

    @property
    def pending(self):
        return self._pending

    @property
    def progress(self):
        """0.0..1.0 progress toward confirmation for the current pending gesture."""
        if self._pending is None:
            return 0.0
        elapsed = self._clock() - self._pending_since
        return min(elapsed / Config.GESTURE_CONFIRMATION_SECONDS, 1.0)

    def reset(self):
        self._pending = None
        self._last_confirmed = None

    def feed(self, gesture):
        """Feed a freshly-observed gesture (or None for 'no hand')."""
        if gesture is None:
            # Hand lost: clear debounce state but DON'T clear last_confirmed
            # so that releasing-and-re-showing the same gesture can re-fire.
            self._pending = None
            self._last_confirmed = None
            return

        if gesture != self._pending:
            self._pending = gesture
            self._pending_since = self._clock()
            return

        if self.progress < 1.0:
            return

        if self._last_confirmed == gesture:
            return  # already fired this hold

        elapsed = self._clock() - self._pending_since
        if gesture == Gesture.START_RECORDING:
            logger.info(f"Gesture confirmed ({elapsed:.1f}s): START")
            self._on_start()
        elif gesture == Gesture.STOP_RECORDING:
            logger.info(f"Gesture confirmed ({elapsed:.1f}s): STOP")
            self._on_stop()
        self._last_confirmed = gesture

def classify_landmarks(landmarks):
    """
    Classify a single hand's landmarks into a Gesture (or None).

    Pure function — takes any sequence of objects with `.y` attributes
    indexed by MediaPipe HandLandmark IDs. Has no mediapipe dependency,
    which makes it trivially unit-testable.
    """
    if not landmarks:
        return None

    def extended(tip_idx, pip_idx):
        # In image-space y, tip "above" pip means tip.y < pip.y
        return landmarks[tip_idx].y < landmarks[pip_idx].y

    index_ext = extended(*_FINGERS["index"])
    middle_ext = extended(*_FINGERS["middle"])
    ring_ext = extended(*_FINGERS["ring"])
    pinky_ext = extended(*_FINGERS["pinky"])

    # Peace sign: index + middle up, ring + pinky down
    if index_ext and middle_ext and not ring_ext and not pinky_ext:
        return Gesture.START_RECORDING
    # Open palm: all four extended
    if index_ext and middle_ext and ring_ext and pinky_ext:
        return Gesture.STOP_RECORDING
    return None


class GestureDetector:
    """MediaPipe-backed gesture detector. Imports mediapipe lazily so the
    rest of this module is testable without the native dependency."""

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self._mp = mp
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)
        self._last_ts_ms = 0

    def detect_gesture(self, image):
        """Process a BGR frame; return (gesture_or_None, landmarks)."""
        rgb_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=image)

        # MediaPipe VIDEO mode requires *strictly* increasing timestamps.
        # Use a monotonic clock and bump forward on collision so NTP/DST
        # jumps can never wind the clock backwards mid-stream.
        ts = time.monotonic_ns() // 1_000_000
        if ts <= self._last_ts_ms:
            ts = self._last_ts_ms + 1
        self._last_ts_ms = ts

        detection_result = self.detector.detect_for_video(rgb_image, ts)

        landmarks = detection_result.hand_landmarks[0] if detection_result.hand_landmarks else []
        return classify_landmarks(landmarks), landmarks

