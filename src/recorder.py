import cv2
import time
import os
import datetime
import logging
from src.config import Config
import shutil
import glob

logger = logging.getLogger(__name__)

class VideoRecorder:
    """
    Writes mp4 segments to disk. The standalone upload_watcher process is
    responsible for uploading them — this class never touches S3.
    """

    def __init__(
        self,
        output_dir=Config.RECORDINGS_DIR,
        width=Config.FRAME_WIDTH,
        height=Config.FRAME_HEIGHT,
        fps=Config.FPS,
    ):
        self.output_dir = output_dir
        self.width = width
        self.height = height
        self.fps = fps
        self.is_recording = False
        self.writer = None
        self.start_time = None
        self.frame_count = 0
        self.current_file_path = None

        os.makedirs(self.output_dir, exist_ok=True)

    def start_recording(self):
        if self.is_recording:
            return
        
        if not self._ensure_disk_space():
            logger.error("Disk Full and Cleanup Failed! Cannot start recording.")
            return

        self.is_recording = True
        self._start_new_file()
        logger.info("Recording Started.")

    def _ensure_disk_space(self):
        """
        Ensures there is enough disk space. 
        If disk usage > CONFIG.MAX_DISK_USAGE_PERCENT, deletes oldest recordings.
        Returns True if space is available (or made available), False if critical failure.
        """
        try:
            while True:
                total, used, free = shutil.disk_usage(self.output_dir)
                percent = (used / total) * 100
                
                if percent < Config.MAX_DISK_USAGE_PERCENT:
                    return True
                
                # Disk is full, try to delete oldest file
                logger.warning(f"Disk usage {percent:.1f}% > {Config.MAX_DISK_USAGE_PERCENT}%. Cleaning up...")
                
                files = glob.glob(os.path.join(self.output_dir, "*.mp4"))
                if not files:
                    logger.error("Disk full and no files to delete!")
                    return False
                
                # Sort by modification time (oldest first)
                oldest_file = min(files, key=os.path.getmtime)
                try:
                    os.remove(oldest_file)
                    logger.info(f"Deleted oldest file to free space: {oldest_file}")
                except OSError as e:
                    logger.error(f"Failed to delete {oldest_file}: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error in disk space check: {e}")
            return False

    def stop_recording(self):
        if not self.is_recording:
            return
        
        self.is_recording = False
        self._close_file()
        logger.info("Recording Stopped.")

    def _start_new_file(self):
        # Re-check disk space at every rollover, not just at start_recording —
        # a long session that crosses the threshold mid-stream would otherwise
        # fill the disk until writes fail.
        if not self._ensure_disk_space():
            logger.error("Disk full at segment rollover; stopping recording.")
            self.is_recording = False
            self.writer = None
            self.current_file_path = None
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rec_{timestamp}.mp4"
        self.current_file_path = os.path.join(self.output_dir, filename)

        # Codec Selection Strategy: try AVC1 (H.264) -> MP4V -> MJPG.
        # Open the real output path each time and keep the first writer that
        # actually opens. Failed attempts are explicitly cleaned up so we
        # never leave a zero-byte file behind for the upload watcher to find.
        for codec in ('avc1', 'mp4v', 'MJPG'):
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(self.current_file_path, fourcc, self.fps, (self.width, self.height))
            if writer.isOpened():
                self.writer = writer
                logger.info(f"Initialized video writer with codec: {codec}")
                break
            writer.release()
            if os.path.exists(self.current_file_path):
                try:
                    os.remove(self.current_file_path)
                except OSError:
                    pass
        else:
            logger.error("Failed to initialize any video writer codec.")
            self.writer = None
            self.is_recording = False
            self.current_file_path = None
            return

        self.start_time = time.time()
        self.frame_count = 0
        logger.info(f"New segment started: {self.current_file_path}")

    def _close_file(self):
        if self.writer:
            self.writer.release()
            self.writer = None
        # The upload_watcher process picks up finalised files from disk.
        self.current_file_path = None

    def write_frame(self, frame):
        if not self.is_recording or self.writer is None:
            return

        self.writer.write(frame)
        self.frame_count += 1

        # Use frame count instead of time.time() for rollover — avoids a syscall
        # in the hot path and keeps segments deterministic relative to FPS.
        if self.frame_count >= self.fps * Config.RECORDING_SEGMENT_DURATION:
            logger.info("Segment duration reached. Rolling over.")
            self._close_file()
            self._start_new_file()
