import mediapipe as mp
import time
import os
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Model Path
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "hand_landmarker.task")

class GestureDetector:
    def __init__(self):
        # Create an HandLandmarker object.
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5)
        
        self.detector = vision.HandLandmarker.create_from_options(options)

    def detect_gesture(self, image):
        """
        Processes the image and returns (gesture_string, landmarks).
        """
        # Convert the BGR image to RGB
        rgb_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image)
        
        # Calculate timestamp (monotonic)
        # MediaPipe requires purely increasing timestamps in VIDEO mode
        # We can use time.time() * 1000 converted to int
        timestamp_ms = int(time.time() * 1000)
        
        # Detect
        detection_result = self.detector.detect_for_video(rgb_image, timestamp_ms)
        
        # Analyze
        gesture = self._analyze_landmarks(detection_result)
        
        # Extract landmarks for visualization (if any)
        landmarks_list = []
        if detection_result.hand_landmarks:
             # Convert NormalizedLandmark objects to simple list of dicts or just pass object if picklable
             # For now, let's pass the raw list of NormalizedLandmark objects 
             # (but be careful about pickling across processes - better to convert to primitives if needed)
             # We'll stick to returning the raw object list for now.
             landmarks_list = detection_result.hand_landmarks[0]

        return gesture, landmarks_list

    def _analyze_landmarks(self, results):
        """
        Analyzes landmarks to return a gesture string.
        """
        if not results.hand_landmarks:
             return None
             
        # Get first hand
        lm = results.hand_landmarks[0]
        
        # Helper to get Y coord (NormalizedLandmark has x, y, z)
        # Finger Tips: 8(Index), 12(Middle), 16(Ring), 20(Pinky)
        # Finger PIPs: 6(Index), 10(Middle), 14(Ring), 18(Pinky)
        
        def is_extended(tip_idx, pip_idx):
            return lm[tip_idx].y < lm[pip_idx].y
            
        index_ext = is_extended(8, 6)
        middle_ext = is_extended(12, 10)
        ring_ext = is_extended(16, 14)
        pinky_ext = is_extended(20, 18)
        
        # 1. Start Recording: "Peace Sign"
        # Index and Middle are UP. Ring and Pinky are DOWN.
        if index_ext and middle_ext and not ring_ext and not pinky_ext:
            return "START_RECORDING"
        
        # 2. Stop Recording: "Open Palm"
        if index_ext and middle_ext and ring_ext and pinky_ext:
            return "STOP_RECORDING"
            
        return None

