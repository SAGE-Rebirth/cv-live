import multiprocessing
from multiprocessing import shared_memory
import numpy as np
import logging
from src.config import Config

logger = logging.getLogger(__name__)

class SharedStateManager:
    def __init__(self, width=Config.FRAME_WIDTH, height=Config.FRAME_HEIGHT):
        self.width = width
        self.height = height
        self.frame_shape = (height, width, 3)
        self.frame_size = int(np.prod(self.frame_shape))
        
        # Shared Memory for 1 Frame (Double buffering would be better but keeping it simple for now)
        # Actually, let's use a standard single buffer lock-protected or just accepted tearing for speed.
        # Ideally: Ring buffer. But let's start with one atomic buffer.
        
        try:
            self.shm = shared_memory.SharedMemory(create=True, size=self.frame_size)
        except FileExistsError:
            # Clean up previous run mess
            try:
                temp = shared_memory.SharedMemory(name=None, size=self.frame_size)
                temp.unlink()
            except:
                pass
            self.shm = shared_memory.SharedMemory(create=True, size=self.frame_size)

        # Create numpy array backed by shared memory
        self.shared_frame = np.ndarray(self.frame_shape, dtype=np.uint8, buffer=self.shm.buf)
        
        # Coordination Flags
        self.new_frame_event = multiprocessing.Event()
        self.running_flag = multiprocessing.Value('b', True)
        self.recording_flag = multiprocessing.Value('b', False)
        self.frame_index = multiprocessing.Value('L', 0) # Unsigned Long

    def get_frame(self):
        """Read current frame from shared memory."""
        # Note: This might read while writing happens (tearing), but for CV it's usually fine 
        # vs the cost of locking.
        return self.shared_frame.copy()

    def write_frame(self, frame):
        """Write frame to shared memory."""
        if frame.shape == self.frame_shape:
            self.shared_frame[:] = frame[:]
            with self.frame_index.get_lock():
                self.frame_index.value += 1
            self.new_frame_event.set()

    def cleanup(self):
        """Release shared memory."""
        try:
            self.shm.close()
            self.shm.unlink()
        except Exception as e:
            logger.error(f"Error cleaning up shared memory: {e}")
