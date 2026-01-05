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
    def __init__(self, output_dir=Config.RECORDINGS_DIR, width=Config.FRAME_WIDTH, height=Config.FRAME_HEIGHT, fps=Config.FPS, upload_callback=None):
        self.output_dir = output_dir
        self.width = width
        self.height = height
        self.fps = fps
        self.is_recording = False
        self.writer = None
        self.start_time = None
        self.current_file_path = None
        self.upload_callback = upload_callback 
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

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
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rec_{timestamp}.mp4"
        self.current_file_path = os.path.join(self.output_dir, filename)
        
        # Codec Selection Strategy
        # Try AVC1 (H.264) -> MP4V (MPEG-4) -> MJPG (Motion JPEG)
        codecs = ['avc1', 'mp4v', 'MJPG']
        self.writer = None
        
        for codec in codecs:
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                test_path = os.path.join(self.output_dir, f"test_{codec}.mp4")
                
                # Try initializing
                # Note: OpenCV doesn't always throw error on init, needs write.
                # But we'll trust the preference order.
                self.writer = cv2.VideoWriter(self.current_file_path, fourcc, self.fps, (self.width, self.height))
                
                if self.writer.isOpened():
                    logger.info(f"Initialized video writer with codec: {codec}")
                    break
            except Exception as e:
                logger.warning(f"Failed to init codec {codec}: {e}")
                continue
                
        if not self.writer or not self.writer.isOpened():
            logger.error("Failed to initialize any video writer codec.")
            self.is_recording = False
            return

        self.start_time = time.time()
        logger.info(f"New segment started: {self.current_file_path}")

    def _close_file(self):
        if self.writer:
            self.writer.release()
            self.writer = None
        
        if self.current_file_path and os.path.exists(self.current_file_path):
            if self.upload_callback:
                self.upload_callback(self.current_file_path)
        
        self.current_file_path = None

    def write_frame(self, frame):
        if not self.is_recording:
            return

        if self.writer:
            self.writer.write(frame)

        if time.time() - self.start_time >= Config.RECORDING_SEGMENT_DURATION:
            logger.info("Segment duration reached. Rolling over.")
            self._close_file()
            self._start_new_file()
