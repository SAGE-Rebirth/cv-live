import multiprocessing
from multiprocessing import shared_memory
import numpy as np
import logging
from src.config import Config

logger = logging.getLogger(__name__)

SHM_NAME = "cv_live_frame"


class SharedStateManager:
    def __init__(self, width=Config.FRAME_WIDTH, height=Config.FRAME_HEIGHT):
        self.width = width
        self.height = height
        self.frame_shape = (height, width, 3)
        self.frame_size = int(np.prod(self.frame_shape))

        # Single shared-memory frame buffer. We use a deterministic name so a
        # leaked segment from a previous crash can be unlinked and recreated.
        try:
            self.shm = shared_memory.SharedMemory(
                create=True, size=self.frame_size, name=SHM_NAME
            )
        except FileExistsError:
            logger.warning(
                f"Shared memory '{SHM_NAME}' already exists (likely from a "
                f"previous crash). Unlinking and recreating."
            )
            stale = shared_memory.SharedMemory(name=SHM_NAME)
            stale.close()
            stale.unlink()
            self.shm = shared_memory.SharedMemory(
                create=True, size=self.frame_size, name=SHM_NAME
            )

        # Create numpy array backed by shared memory
        self.shared_frame = np.ndarray(self.frame_shape, dtype=np.uint8, buffer=self.shm.buf)
        
        # Coordination Flags
        self.running_flag = multiprocessing.Value('b', True)
        self.recording_flag = multiprocessing.Value('b', False)
        self.frame_index = multiprocessing.Value('L', 0) # Unsigned Long
        # Live-tunable camera FPS. The capture process polls this and
        # reopens the camera when it changes. Initialized from Config.
        self.target_fps = multiprocessing.Value('i', int(Config.FPS))
        # Actual FPS reported by the camera driver after opening. The
        # recorder must use THIS value (not target_fps) for the MP4 header,
        # otherwise playback speed is wrong when the driver ignores our request.
        self.actual_fps = multiprocessing.Value('i', int(Config.FPS))
        # Shared detection rate so dashboard changes propagate to the
        # inference child without requiring it to re-read Config / YAML.
        self.target_detection_rate = multiprocessing.Value('i', int(Config.DETECTION_RATE))
        # When False the inference process sleeps instead of running
        # MediaPipe — zero CPU with no process terminate/respawn.
        self.inference_enabled = multiprocessing.Value('b', False)

        # Per-consumer wakeup events. Each consumer (main loop, inference, ...)
        # registers and gets its own Event so the producer can wake all of them
        # without consumers stealing wakeups from each other. Must be registered
        # BEFORE child processes are started (spawn pickles the manager).
        self._consumer_events = []

    def refresh(self):
        """
        Re-link the numpy array to the shared memory buffer.
        Must be called in child processes after 'spawn'.
        """
        # In spawn mode, self.shm is a valid handle (recreated by pickling machinery),
        # but self.shared_frame likely became a copy of data during pickle.
        # We discard the copy and create a new view on the shared buffer.
        self.shared_frame = np.ndarray(self.frame_shape, dtype=np.uint8, buffer=self.shm.buf)

    def register_consumer(self):
        """
        Allocate a wakeup Event for a new consumer. Call this from the main
        process BEFORE spawning child processes that will wait on it.
        """
        evt = multiprocessing.Event()
        self._consumer_events.append(evt)
        return evt

    def get_frame(self):
        """Read current frame from shared memory (returns a copy)."""
        # Tearing is acceptable for CV throughput vs. the cost of locking.
        return self.shared_frame.copy()

    def peek_frame(self):
        """
        Return a zero-copy view onto the shared buffer. The caller MUST NOT
        mutate or hold this view across iterations — use this only for
        read-only consumers (e.g. inference) that immediately hand the array
        to a library that copies internally.
        """
        return self.shared_frame

    def write_frame(self, frame):
        """Write frame to shared memory and wake all registered consumers."""
        if frame.shape != self.frame_shape:
            logger.warning(
                f"Frame shape mismatch: got {frame.shape}, expected {self.frame_shape}. "
                f"Frame dropped."
            )
            return
        self.shared_frame[:] = frame[:]
        with self.frame_index.get_lock():
            self.frame_index.value += 1
        for evt in self._consumer_events:
            evt.set()

    def cleanup(self):
        """Release shared memory."""
        try:
            self.shm.close()
            self.shm.unlink()
        except Exception as e:
            logger.error(f"Error cleaning up shared memory: {e}")
