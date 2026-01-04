import multiprocessing
import cv2
import time
import logging
import queue
from src.gesture import GestureDetector
from src.config import Config
from src.thermal import get_cpu_temperature

logger = logging.getLogger(__name__)

class InferenceProcess(multiprocessing.Process):
    def __init__(self, shared_state, result_queue):
        super().__init__()
        self.shared_state = shared_state
        self.result_queue = result_queue # To send back (gesture_name, landmarks)
        self.daemon = True

    def run(self):
        logger.info("InferenceProcess Started.")
        detector = GestureDetector()
        
        last_processed_index = -1
        current_detection_rate = Config.DETECTION_RATE
        frame_counter = 0

        while self.shared_state.running_flag.value:
            # Check if new frame is available
            current_index = self.shared_state.frame_index.value
            
            if current_index == last_processed_index:
                time.sleep(0.005)
                continue
            
            # Thermal Throttling Logic
            if frame_counter % 100 == 0:
                temp = get_cpu_temperature()
                if temp > 75.0:
                    current_detection_rate = Config.DETECTION_RATE * 2
                elif temp < 60.0:
                    current_detection_rate = Config.DETECTION_RATE

            frame_counter += 1
            
            # Skip frames logic
            if frame_counter % current_detection_rate != 0:
                last_processed_index = current_index
                continue

            # Process Frame
            frame = self.shared_state.get_frame() # Zero-copy read
            
            # Convert for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb_frame)
            gesture = detector.detect_gesture(results)
            
            # Put result in queue
            # We can't pickle the whole 'results' object easily usually?
            # MediaPipe results are complex C++ wrappers.
            # We should extract what we need: landmarks list.
            
            # Simplified result for IPC
            if results and results.multi_hand_landmarks:
                 # Serialize landmarks to simple list of dicts/arrays
                 # For simplicity now, let's just send the gesture string
                 # If we need visualization, we need coordinates.
                 pass
            
            try:
                # Sending: (frame_index, gesture, has_landmarks)
                # To draw landmarks in main process, we would need to serialize them
                # For now, let's just send the gesture to control recording.
                if gesture:
                    self.result_queue.put(gesture, block=False)
            except queue.Full:
                pass
            
            last_processed_index = current_index
        
        logger.info("InferenceProcess Stopped.")
