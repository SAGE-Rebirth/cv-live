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
        self.shared_state.refresh() # Re-link shared memory
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
            
            # Convert for MediaPipe (BGR to RGB is handled inside detect_gesture now if needed, 
            # actually prompt said to just call detect_gesture(frame). 
            # But wait, my implementation of detect_gesture EXPECTS BGR and converts it. 
            # Yes, lines 27-28 in new gesture.py: "Convert the BGR image to RGB".
            # So we pass BGR frame directly.
            
            # Old code converted it here. New code converts inside.
            # So pass 'frame' directly.
            
            try:
                gesture, landmarks = detector.detect_gesture(frame)
                
                # Send result
                if gesture:
                    # Currently Service expects just the string.
                    # We will send just the string to preserve compatibility.
                    # If we want to send landmarks later, we need to update Service.
                    self.result_queue.put(gesture, block=False)
            except Exception as e:
                logger.error(f"Inference Error: {e}")
                
            last_processed_index = current_index
            
            last_processed_index = current_index
        
        logger.info("InferenceProcess Stopped.")
