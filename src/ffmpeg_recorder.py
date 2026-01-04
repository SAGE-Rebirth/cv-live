import subprocess
import threading
import queue
import time
import os
import datetime
import logging
import shutil
import atexit
import signal
import glob
from src.config import Config

logger = logging.getLogger(__name__)

class FFmpegRecorder:
    def __init__(self, output_dir=Config.RECORDINGS_DIR, width=Config.FRAME_WIDTH, height=Config.FRAME_HEIGHT, fps=Config.FPS):
        self.output_dir = output_dir
        self.width = width
        self.height = height
        self.fps = fps
        
        self.is_recording = False
        self.frame_queue = queue.Queue(maxsize=300) 
        self.record_thread = None
        self.process = None
        self.current_file_path = None
        self.start_time = None
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        # Register cleanup to kill subprocess on exit
        atexit.register(self._cleanup)

    def _cleanup(self):
        # Called on script exit
        if self.process:
            try:
                logger.warning("Emergency Cleanup: Killing FFmpeg process")
                self.process.kill()
            except:
                pass

    def start_recording(self):
        if self.is_recording:
            return
        
        if not self._ensure_disk_space():
            logger.error("Disk Full and Cleanup Failed! Cannot start recording.")
            return

        self.is_recording = True
        self.start_time = time.time()
        
        self.record_thread = threading.Thread(target=self._writer_loop)
        self.record_thread.daemon = True
        self.record_thread.start()
        logger.info("Recording Started (Threaded FFmpeg).")

    def stop_recording(self):
        if not self.is_recording:
            return
        
        self.is_recording = False
        if self.record_thread:
            self.record_thread.join(timeout=5.0) # Wait max 5s
            if self.record_thread.is_alive():
                logger.error("Writer thread stuck! Force killing process.")
                self._close_ffmpeg_process()
        
        logger.info("Recording Stopped.")

    def write_frame(self, frame):
        if not self.is_recording:
            return
        
        try:
            self.frame_queue.put(frame, block=False)
        except queue.Full:
            logger.warning("Frame Dropped! Write queue full.")

        if time.time() - self.start_time >= Config.RECORDING_SEGMENT_DURATION:
             self._rotate_segment()

    def _rotate_segment(self):
        logger.info("Segment duration reached. Rotating...")
        self.frame_queue.put("ROTATE")
        self.start_time = time.time()

    def _writer_loop(self):
        self._start_ffmpeg_process()
        
        while True:
            try:
                item = self.frame_queue.get(timeout=1.0)
            except queue.Empty:
                if not self.is_recording:
                    break
                continue
            
            if item == "ROTATE":
                self._close_ffmpeg_process()
                self._start_ffmpeg_process()
                continue
            
            # Writing logic
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(item.tobytes())
                except BrokenPipeError:
                    logger.error("FFmpeg Broken Pipe! Process died?")
                    self.process = None
                    # Try to restart?
                    # self._start_ffmpeg_process()
                except Exception as e:
                    logger.error(f"Error writing to ffmpeg: {e}")
            
            if not self.is_recording and self.frame_queue.empty():
                break

        self._close_ffmpeg_process()

    def _start_ffmpeg_process(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rec_{timestamp}.mp4"
        self.current_file_path = os.path.join(self.output_dir, filename)
        
        cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{self.width}x{self.height}',
            '-pix_fmt', 'bgr24',
            '-r', str(self.fps),
            '-i', '-',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            self.current_file_path
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            logger.info(f"FFmpeg process started: {self.current_file_path}")
        except FileNotFoundError:
            logger.critical("FFmpeg NOT FOUND!")
            self.process = None

    def _close_ffmpeg_process(self):
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not exit cleanly. Killing...")
                self.process.kill()
            except Exception as e:
                logger.error(f"Error closing FFmpeg: {e}")

            logger.info(f"Closed file: {self.current_file_path}")
            self.process = None
            self.current_file_path = None

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
