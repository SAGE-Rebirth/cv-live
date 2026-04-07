import multiprocessing
import cv2
import time
import logging
from src.config import Config
from src.logging_setup import setup_logging

logger = logging.getLogger(__name__)

class CaptureProcess(multiprocessing.Process):
    def __init__(self, shared_state, camera_index=Config.CAMERA_INDEX):
        super().__init__()
        self.shared_state = shared_state
        self.camera_index = camera_index
        self.daemon = True # Kill when main dies

    def _open_camera(self):
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, Config.FPS)
        # Critical: keep the driver buffer at 1 frame so we never serve stale
        # frames after a brief consumer stall. This is the single biggest
        # latency win on Pi/V4L2 backends.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def run(self):
        setup_logging("CAPTURE")
        self.shared_state.refresh() # Re-link shared memory
        logger.info("CaptureProcess Started.")
        cap = self._open_camera()

        while self.shared_state.running_flag.value:
            ret, frame = cap.read()
            if ret:
                # Force resize to match shared memory expectation
                if frame.shape != self.shared_state.frame_shape:
                    frame = cv2.resize(frame, (Config.FRAME_WIDTH, Config.FRAME_HEIGHT))
                self.shared_state.write_frame(frame)
            else:
                logger.warning("CaptureProcess: Failed to grab frame. Reconnecting...")
                cap.release()
                time.sleep(1.0)
                cap = self._open_camera()

        cap.release()
        logger.info("CaptureProcess Stopped.")
