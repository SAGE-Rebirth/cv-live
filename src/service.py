import cv2
import threading
import time
import logging
import multiprocessing
import queue

from src.recorder import VideoRecorder
from src.config import Config
from src.gesture import GestureDebouncer
from src.processes.shared_state import SharedStateManager
from src.processes.capture import CaptureProcess
from src.processes.inference import InferenceProcess

logger = logging.getLogger(__name__)


class CameraService:
    """
    Owns the multi-process pipeline. Uploads are NOT this service's job —
    the recorder writes mp4 segments to disk and the standalone upload_watcher
    process is the sole owner of S3 uploads. This separation means a crash
    in the camera service never loses pending uploads.
    """

    def __init__(self, bucket_name):
        # bucket_name kept for API compatibility but no longer used here.
        self.bucket_name = bucket_name
        self.running = False

        # Components
        self.recorder = VideoRecorder(
            output_dir=Config.RECORDINGS_DIR,
            width=Config.FRAME_WIDTH,
            height=Config.FRAME_HEIGHT,
            fps=Config.FPS,
        )
        self.debouncer = GestureDebouncer(
            on_start=self.recorder.start_recording,
            on_stop=self.recorder.stop_recording,
        )

        # Multi-Processing Components
        self.shared_state = SharedStateManager()
        self.result_queue = multiprocessing.Queue(maxsize=2)

        # Per-consumer wakeup events MUST be registered before children spawn
        self._main_wakeup = self.shared_state.register_consumer()
        self._inference_wakeup = self.shared_state.register_consumer()

        self.capture_process = CaptureProcess(self.shared_state, Config.CAMERA_INDEX)
        self.inference_process = InferenceProcess(
            self.shared_state, self.result_queue, self._inference_wakeup
        )

        self.processing_thread = None
        # Condition that gates MJPEG viewers — they wait() and the main loop
        # notifies after each fresh JPEG encode. No polling, no busy loops.
        self.frame_condition = threading.Condition()
        self.current_frame = None

    @property
    def lock(self):
        # Backwards-compat shim: code that used `with service.lock:` now uses
        # the underlying condition's lock. Prefer frame_condition directly.
        return self.frame_condition

    def get_status(self):
        """Returns the current status of the service."""
        return {
            "recording": self.recorder.is_recording
        }

    def toggle_recording(self, state: bool):
        """Manually toggle recording state."""
        if state:
            self.recorder.start_recording()
        else:
            self.recorder.stop_recording()

    def apply_runtime_change(self, key: str, value):
        """
        Hook called after Config.update_setting() succeeds. Pushes the new
        value into whichever component owns it via shared multiprocessing
        Values so child processes see the change immediately.
        """
        if key == "FPS":
            new_fps = int(value)
            self.shared_state.target_fps.value = new_fps
            # Don't reconfigure the recorder here — the capture process will
            # reopen the camera and publish the ACTUAL fps the driver settled
            # on. The main loop picks that up and reconfigures the recorder
            # with the real value, so the MP4 header matches reality.
        elif key == "DETECTION_RATE":
            self.shared_state.target_detection_rate.value = int(value)

    def _draw_overlay(self, frame, last_gesture):
        """Draw recording status + gesture confirmation progress."""
        cv2.putText(
            frame, f"REC: {self.recorder.is_recording}", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
            (0, 0, 255) if self.recorder.is_recording else (0, 255, 0), 2,
        )

        if not last_gesture:
            return

        if self.debouncer.pending == last_gesture:
            progress = self.debouncer.progress
            if progress < 1.0:
                color = (0, 165, 255)
                text = f"{last_gesture.value}: {int(progress * 100)}%"
            else:
                color = (0, 255, 0)
                text = f"{last_gesture.value}: CONFIRMED"
            cv2.putText(frame, text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        else:
            cv2.putText(
                frame, f"Gesture: {last_gesture.value}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2,
            )

    def start(self):
        if self.running:
            return

        logger.info("Starting Multi-Process Camera Service...")
        self.running = True
        self.shared_state.running_flag.value = True

        # Start Child Processes
        self.capture_process.start()
        self.inference_process.start()

        # Start Main Loop (in this process)
        self.processing_thread = threading.Thread(target=self._main_loop)
        self.processing_thread.start()

    def _check_children(self):
        """Detect crashed child processes and respawn them.

        Called periodically from the main loop.  If a child has died the
        corresponding ``multiprocessing.Process`` object can't be restarted,
        so we create a fresh instance (re-using the same shared-state and
        wakeup event) and start it.
        """
        if not self.capture_process.is_alive():
            logger.error("CaptureProcess died — respawning.")
            self.capture_process = CaptureProcess(
                self.shared_state, Config.CAMERA_INDEX
            )
            self.capture_process.start()

        if not self.inference_process.is_alive():
            logger.error("InferenceProcess died — respawning.")
            self.inference_process = InferenceProcess(
                self.shared_state, self.result_queue, self._inference_wakeup
            )
            self.inference_process.start()

    def stop(self):
        logger.info("Stopping components...")
        self.running = False
        self.shared_state.running_flag.value = False

        if self.recorder.is_recording:
            self.recorder.stop_recording()

        self.processing_thread.join()
        self.capture_process.join(timeout=5)
        self.inference_process.join(timeout=5)
        # Force-kill children that didn't exit within the timeout.
        for p in (self.capture_process, self.inference_process):
            if p.is_alive():
                logger.warning(f"Force-killing {p.name}")
                p.kill()
        self.shared_state.cleanup()
        logger.info("Service Stopped.")

    def _main_loop(self):
        last_gesture = None
        last_frame_index = -1
        # Throttle MJPEG encoding to at most 25 FPS — anything faster is
        # wasted bandwidth + CPU. We re-derive this from the recorder fps
        # on every loop so live FPS changes from the dashboard apply.
        last_encode_time = 0.0
        last_health_check = 0.0

        while self.running:
            # Block until producer signals a new frame (1s timeout for shutdown checks)
            self._main_wakeup.wait(timeout=1.0)
            self._main_wakeup.clear()

            # Periodic child-process health check (~every 5 seconds).
            now_hc = time.time()
            if now_hc - last_health_check >= 5.0:
                last_health_check = now_hc
                self._check_children()

            current_index = self.shared_state.frame_index.value
            if current_index == last_frame_index:
                continue  # spurious wakeup or shutdown
            last_frame_index = current_index

            # Keep the recorder's FPS in sync with what the camera driver
            # actually provides. The capture process writes actual_fps after
            # every camera open — if it differs from the recorder, roll over.
            actual = self.shared_state.actual_fps.value
            if actual > 0 and actual != self.recorder.fps:
                logger.info(f"Syncing recorder FPS to actual camera FPS: {self.recorder.fps} -> {actual}")
                self.recorder.reconfigure_fps(actual)

            # Need a writable copy because we draw overlays / hand it to the recorder
            try:
                frame = self.shared_state.get_frame()
            except Exception:
                continue

            # Drain new inference events into last_gesture. Inference only
            # emits state CHANGES (peace -> none -> peace), so the queue
            # may stay empty for many frames while the user holds a gesture.
            while True:
                try:
                    last_gesture = self.result_queue.get_nowait()
                except queue.Empty:
                    break

            # Feed the debouncer EVERY frame with the current state, not
            # only on queue events. The debouncer is a clock-driven state
            # machine — without continuous ticks it can never observe that
            # the hold time has elapsed, and the gesture would never fire.
            self.debouncer.feed(last_gesture)

            self._draw_overlay(frame, last_gesture)

            # Pipe to Recorder
            if self.recorder.is_recording:
                self.recorder.write_frame(frame)

            # Throttled JPEG encode for the MJPEG stream — capped at 25 FPS
            encode_interval = 1.0 / min(max(self.recorder.fps, 1), 25)
            now = time.time()
            if now - last_encode_time >= encode_interval:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    with self.frame_condition:
                        self.current_frame = buffer.tobytes()
                        self.frame_condition.notify_all()
                    last_encode_time = now

        # On shutdown, wake any blocked viewers so their generators can exit.
        with self.frame_condition:
            self.frame_condition.notify_all()
