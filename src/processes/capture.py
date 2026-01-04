import multiprocessing
import cv2
import time
import logging
import numpy as np
from src.config import Config

logger = logging.getLogger(__name__)

class CaptureProcess(multiprocessing.Process):
    def __init__(self, shared_state, camera_index=Config.CAMERA_INDEX):
        super().__init__()
        self.shared_state = shared_state
        self.camera_index = camera_index
        self.daemon = True # Kill when main dies

    def run(self):
        logger.info(f"CaptureProcess Started on Core: {multiprocessing.cpu_count()}")
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, Config.FPS)
        
        while self.shared_state.running_flag.value:
            ret, frame = cap.read()
            if ret:
                # Direct write to shared memory
                # We need to ensure connection is correct (BGR)
                self.shared_state.write_frame(frame)
            else:
                logger.warning("CaptureProcess: Failed to grab frame.")
                time.sleep(0.1)
                
                # Simple reconnect logic
                cap.release()
                time.sleep(1.0)
                cap = cv2.VideoCapture(self.camera_index)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
                cap.set(cv2.CAP_PROP_FPS, Config.FPS)
        
        cap.release()
        logger.info("CaptureProcess Stopped.")
