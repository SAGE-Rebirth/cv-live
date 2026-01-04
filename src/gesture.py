import mediapipe as mp

class GestureDetector:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.mp_draw = mp.solutions.drawing_utils

    def process(self, image):
        """Processes the image and returns MediaPipe results."""
        results = self.hands.process(image)
        return results

    def _is_finger_extended(self, landmarks, tip_idx, pip_idx):
        """
        Returns True if the finger tip is higher (lower Y value) than the PIP joint.
        Assumes an upright hand position.
        """
        return landmarks[tip_idx].y < landmarks[pip_idx].y

    def detect_gesture(self, results):
        """
        Analyzes landmarks to return a gesture string:
        - "START_RECORDING": Peace Sign (Index + Middle extended).
        - "STOP_RECORDING": Open Palm (At least 4 fingers extended).
        - None: No specific gesture detected.
        """
        if not results.multi_hand_landmarks:
            return None

        # Only check the first hand detected
        lm = results.multi_hand_landmarks[0].landmark
        
        # Check extensions for non-thumb fingers (Index to Pinky)
        # 8: Index Tip, 6: Index PIP
        index_ext = self._is_finger_extended(lm, 8, 6)
        # 12: Middle Tip, 10: Middle PIP
        middle_ext = self._is_finger_extended(lm, 12, 10)
        # 16: Ring Tip, 14: Ring PIP
        ring_ext = self._is_finger_extended(lm, 16, 14)
        # 20: Pinky Tip, 18: Pinky PIP
        pinky_ext = self._is_finger_extended(lm, 20, 18)
        
        # Thumb Logic:
        # Thumb detection is often noisy depending on hand orientation (palm facing in vs out).
        # We focus on the other 4 fingers for high-confidence triggers.
        
        # Gesture Logic
        
        # 1. Start Recording: "Peace Sign"
        # Index and Middle are UP. Ring and Pinky are DOWN.
        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return "START_RECORDING"
        
        # 2. Stop Recording: "Open Palm" (High Five)
        # All 4 main fingers are UP. 
        # (We ignore thumb to avoid false negatives if thumb is tucked slightly).
        if index_ext and middle_ext and ring_ext and pinky_ext:
            return "STOP_RECORDING"
            
        return None
