import multiprocessing
import cv2
import time
import logging
import queue
from src.gesture import GestureDetector
from src.config import Config
from src.thermal import get_cpu_temperature
from src.logging_setup import setup_logging

logger = logging.getLogger(__name__)

class InferenceProcess(multiprocessing.Process):
    def __init__(self, shared_state, result_queue, wakeup_event):
        super().__init__()
        self.shared_state = shared_state
        self.result_queue = result_queue # To send back gesture strings
        self.wakeup_event = wakeup_event
        self.daemon = True

    def run(self):
        setup_logging("INFER")
        self.shared_state.refresh() # Re-link shared memory
        logger.info("InferenceProcess Started.")

        # Defer MediaPipe init until gestures are actually enabled — avoids
        # loading ~50 MB of native libraries while the user has gestures off.
        detector = None

        last_processed_index = -1
        current_detection_rate = max(1, self.shared_state.target_detection_rate.value)
        frame_counter = 0
        last_sent_gesture = "__init__"  # sentinel: never matches a real value

        while self.shared_state.running_flag.value:
            # When gesture control is disabled, sleep instead of processing.
            # Zero CPU from MediaPipe. Check the flag every second.
            if not self.shared_state.inference_enabled.value:
                self.wakeup_event.wait(timeout=1.0)
                self.wakeup_event.clear()
                continue

            # Lazy-init detector on first enabled tick
            if detector is None:
                logger.info("Initializing MediaPipe detector...")
                detector = GestureDetector()
                logger.info("MediaPipe detector ready.")

            # Block until producer signals a new frame (or 1s timeout for shutdown checks)
            self.wakeup_event.wait(timeout=1.0)
            self.wakeup_event.clear()

            current_index = self.shared_state.frame_index.value
            if current_index == last_processed_index:
                continue  # spurious wakeup or shutdown

            last_processed_index = current_index
            frame_counter += 1

            # Thermal Throttling Logic. Read detection rate from shared state
            # so dashboard changes apply immediately (Config is a stale
            # in-memory copy in this spawned child).
            if frame_counter % 100 == 0:
                base_rate = max(1, self.shared_state.target_detection_rate.value)
                temp = get_cpu_temperature()
                if temp > 75.0:
                    current_detection_rate = base_rate * 2
                else:
                    current_detection_rate = base_rate

            # Skip frames logic
            if frame_counter % current_detection_rate != 0:
                continue

            # Process Frame. We need a stable copy because detect_gesture
            # does BGR→RGB conversion and MediaPipe processing on it.
            frame = self.shared_state.get_frame()
            if frame is None:
                continue

            try:
                gesture, _landmarks = detector.detect_gesture(frame)
            except Exception:
                logger.exception("Inference Error")
                continue

            # Only send when the state changes — including transitions to
            # None ("hand lost") so the consumer's debouncer can reset.
            if gesture != last_sent_gesture:
                logger.info(f"Gesture change: {last_sent_gesture} -> {gesture}")
                try:
                    self.result_queue.put(gesture, block=False)
                    last_sent_gesture = gesture
                except queue.Full:
                    pass  # try again next iteration

        logger.info("InferenceProcess Stopped.")
