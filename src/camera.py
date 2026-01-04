import cv2
import threading
import time
import logging
from src.config import Config

logger = logging.getLogger(__name__)

class ThreadedCamera:
    def __init__(self, src=Config.CAMERA_INDEX):
        self.src = src
        self.cap = None
        self.grabbed = False
        self.frame = None
        self.started = False
        self.read_lock = threading.Lock()
        self.thread = None
        
        self._open_camera()

    def _open_camera(self):
        if self.cap:
            self.cap.release()
            
        logger.info(f"Opening Camera {self.src}...")
        self.cap = cv2.VideoCapture(self.src)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, Config.FPS)
        
        if self.cap.isOpened():
            self.grabbed, self.frame = self.cap.read()
            if self.grabbed:
                logger.info("Camera Opened Successfully.")
            else:
                logger.warning("Camera opened but failed to grab first frame.")
        else:
            logger.error("Failed to open camera.")

    def start(self):
        if self.started:
            return self
        self.started = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def update(self):
        fail_count = 0
        while self.started:
            if self.cap and self.cap.isOpened():
                grabbed, frame = self.cap.read()
                if grabbed:
                    with self.read_lock:
                        self.grabbed = grabbed
                        self.frame = frame
                    fail_count = 0
                else:
                    fail_count += 1
                    logger.warning(f"Failed to grab frame ({fail_count})")
            else:
                 fail_count += 1

            # Auto-Reconnect Logic
            if fail_count > 30: # ~1 second of failures
                logger.error("Camera connection lost. Attempting Reconnect...")
                self._open_camera()
                fail_count = 0
                time.sleep(1.0) # Wait a bit before retrying

            time.sleep(0.001)

    def read(self):
        with self.read_lock:
            if self.frame is None:
                return False, None
            return self.grabbed, self.frame.copy()

    def stop(self):
        self.started = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()
