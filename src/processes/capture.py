import multiprocessing
import cv2
import time
import threading
import logging
from src.config import Config
from src.logging_setup import setup_logging

logger = logging.getLogger(__name__)

# Maximum seconds to wait for cap.read() before treating the camera as hung.
_READ_TIMEOUT = 5.0


class CaptureProcess(multiprocessing.Process):
    def __init__(self, shared_state, camera_index=Config.CAMERA_INDEX):
        super().__init__()
        self.shared_state = shared_state
        self.camera_index = camera_index
        self.daemon = True  # Kill when main dies

    def _open_camera(self, fps):
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, fps)
        # Critical: keep the driver buffer at 1 frame so we never serve stale
        # frames after a brief consumer stall. This is the single biggest
        # latency win on Pi/V4L2 backends.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        # Publish the REAL FPS the driver settled on. The recorder must use
        # this for the MP4 header — otherwise playback speed is wrong.
        real = max(1, int(round(actual_fps))) if actual_fps > 0 else fps
        self.shared_state.actual_fps.value = real
        logger.info(f"Camera opened: requested {fps} FPS, driver reports {actual_fps:.1f}, using {real}")
        return cap

    @staticmethod
    def _read_with_timeout(cap, timeout=_READ_TIMEOUT):
        """Read a frame with a timeout.

        ``cap.read()`` can block indefinitely if the camera disconnects
        mid-stream (common with macOS AVFoundation).  We run it in a
        daemon thread and give up after *timeout* seconds.
        """
        result = [False, None]

        def _grab():
            ret, frame = cap.read()
            result[0] = ret
            result[1] = frame

        t = threading.Thread(target=_grab, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            # cap.read() is stuck — caller should release and reopen.
            logger.warning("cap.read() timed out after %.1fs", timeout)
            return False, None
        return result[0], result[1]

    def run(self):
        setup_logging("CAPTURE")
        self.shared_state.refresh()  # Re-link shared memory
        logger.info("CaptureProcess Started.")

        current_fps = self.shared_state.target_fps.value
        cap = self._open_camera(current_fps)

        while self.shared_state.running_flag.value:
            # Live FPS reload: dashboard writes to target_fps; we reopen
            # the camera if it changed.
            requested_fps = self.shared_state.target_fps.value
            if requested_fps != current_fps:
                logger.info(f"FPS change requested: {current_fps} -> {requested_fps}")
                cap.release()
                current_fps = requested_fps
                cap = self._open_camera(current_fps)

            ret, frame = self._read_with_timeout(cap)
            if ret:
                # Force resize to match shared memory expectation
                if frame.shape != self.shared_state.frame_shape:
                    frame = cv2.resize(frame, (Config.FRAME_WIDTH, Config.FRAME_HEIGHT))
                self.shared_state.write_frame(frame)
            else:
                logger.warning("CaptureProcess: Failed to grab frame. Reconnecting...")
                cap.release()
                time.sleep(1.0)
                cap = self._open_camera(current_fps)

        cap.release()
        logger.info("CaptureProcess Stopped.")
