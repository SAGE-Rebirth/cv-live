import cv2
import time
import os
import threading
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

        # Single lock guards every operation that touches `self.writer`.
        # Without it, the API thread (reconfigure_fps / stop) and the main
        # loop thread (write_frame) can race and either drop frames or
        # crash OpenCV with use-after-release on the VideoWriter.
        self._lock = threading.RLock()

        os.makedirs(self.output_dir, exist_ok=True)

        # Probe codec availability at startup so a broken OpenCV build is
        # caught immediately rather than hours later at first record.
        self._preferred_codec = self._probe_codecs()

    def _probe_codecs(self):
        """Write a tiny test file *with actual frames* to find a working codec.

        Just checking ``isOpened()`` is not enough — on macOS the ``avc1``
        (VideoToolbox) backend opens successfully but silently produces
        0-byte files.  We write a few frames and verify the output has
        non-zero size.
        """
        import numpy as np

        test_path = os.path.join(self.output_dir, ".codec_probe.mp4")
        test_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        for codec in ('avc1', 'mp4v'):
            fourcc = cv2.VideoWriter_fourcc(*codec)
            w = cv2.VideoWriter(
                test_path, fourcc, 10.0, (self.width, self.height)
            )
            if not w.isOpened():
                w.release()
                self._remove_silent(test_path)
                continue

            # Write a handful of frames so the container is finalized.
            for _ in range(5):
                w.write(test_frame)
            w.release()

            size = 0
            try:
                size = os.path.getsize(test_path)
            except OSError:
                pass
            self._remove_silent(test_path)

            if size > 0:
                logger.info(f"Codec probe: using {codec} ({size} bytes test file)")
                return codec
            logger.warning(f"Codec probe: {codec} opened but produced 0 bytes — skipping")

        logger.error(
            "No working video codec found! Recording will fail. "
            "Install opencv-contrib-python or ffmpeg."
        )
        return None

    @staticmethod
    def _remove_silent(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def start_recording(self):
        with self._lock:
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
            # Cap iterations to avoid an infinite loop if deletions don't
            # actually free enough space (e.g. other processes filling disk).
            for _ in range(50):
                total, used, free = shutil.disk_usage(self.output_dir)
                percent = (used / total) * 100

                if percent < Config.MAX_DISK_USAGE_PERCENT:
                    return True

                # Disk is full, try to delete oldest file
                logger.warning(f"Disk usage {percent:.1f}% > {Config.MAX_DISK_USAGE_PERCENT}%. Cleaning up...")

                files = glob.glob(os.path.join(self.output_dir, "*.mp4"))
                if not files:
                    logger.error("Disk full and no recording files to delete!")
                    return False

                # Sort by modification time (oldest first)
                oldest_file = min(files, key=os.path.getmtime)
                try:
                    os.remove(oldest_file)
                    logger.info(f"Deleted oldest file to free space: {oldest_file}")
                except OSError as e:
                    logger.error(f"Failed to delete {oldest_file}: {e}")
                    return False

            logger.error("Disk still full after deleting 50 files — giving up.")
            return False
                    
        except Exception as e:
            logger.error(f"Error in disk space check: {e}")
            return False

    def stop_recording(self):
        with self._lock:
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

        # Sanity-check that the camera params we were given actually make
        # sense — VideoWriter will silently fail to open with junk inputs.
        if self.fps <= 0 or self.width <= 0 or self.height <= 0:
            logger.error(
                f"Refusing to start recorder with invalid params: "
                f"fps={self.fps} width={self.width} height={self.height}"
            )
            self.is_recording = False
            self.writer = None
            self.current_file_path = None
            return

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rec_{timestamp}.mp4"
        self.current_file_path = os.path.abspath(os.path.join(self.output_dir, filename))

        # Use the codec that was validated at init time.
        if self._preferred_codec is None:
            logger.error("No working codec — cannot record.")
            self.writer = None
            self.is_recording = False
            self.current_file_path = None
            return

        fourcc = cv2.VideoWriter_fourcc(*self._preferred_codec)
        writer = cv2.VideoWriter(
            self.current_file_path, fourcc, float(self.fps), (self.width, self.height)
        )
        if not writer.isOpened():
            writer.release()
            logger.error(f"VideoWriter failed to open with {self._preferred_codec}")
            if os.path.exists(self.current_file_path):
                try:
                    os.remove(self.current_file_path)
                except OSError:
                    pass
            self.writer = None
            self.is_recording = False
            self.current_file_path = None
            return

        self.writer = writer
        logger.info(
            f"Recording -> {self.current_file_path} "
            f"(codec={self._preferred_codec}, {self.width}x{self.height} @ {self.fps}fps)"
        )

        self.start_time = time.time()
        self.frame_count = 0

    def _close_file(self):
        path = self.current_file_path
        frames = self.frame_count
        if self.writer:
            self.writer.release()
            self.writer = None

        if path and os.path.exists(path):
            size = os.path.getsize(path)
            if size == 0:
                logger.error(
                    f"Closed segment is 0 bytes — codec failed silently: {path}. "
                    f"Removing the empty file."
                )
                try:
                    os.remove(path)
                except OSError:
                    pass
            else:
                logger.info(
                    f"Segment closed: {path} ({frames} frames, {size / 1024 / 1024:.1f} MB)"
                )
        elif path:
            logger.error(f"Closed segment never made it to disk: {path}")

        # The upload_watcher process picks up finalised files from disk.
        self.current_file_path = None

    def write_frame(self, frame):
        with self._lock:
            if not self.is_recording or self.writer is None:
                return

            # VideoWriter requires the frame size to match exactly what was
            # passed to the constructor — otherwise the write is silently
            # dropped and the file ends up empty. Resize defensively rather
            # than logging on every frame.
            h, w = frame.shape[:2]
            if w != self.width or h != self.height:
                frame = cv2.resize(frame, (self.width, self.height))

            self.writer.write(frame)
            self.frame_count += 1

            # Use wall-clock time for rollover so FPS changes mid-recording
            # don't corrupt the segment duration calculation.
            if (time.time() - self.start_time) >= Config.RECORDING_SEGMENT_DURATION:
                logger.info("Segment duration reached. Rolling over.")
                self._close_file()
                self._start_new_file()

    def reconfigure_fps(self, new_fps: int):
        """
        Apply a new FPS. If we're currently recording, the active segment is
        closed (so it's playable at its original FPS) and a fresh segment is
        opened at the new FPS. Holds the recorder lock so write_frame on
        another thread can't race the close/reopen.
        """
        with self._lock:
            new_fps = int(new_fps)
            if new_fps == self.fps or new_fps <= 0:
                return
            logger.info(f"Recorder FPS change: {self.fps} -> {new_fps}")
            was_recording = self.is_recording
            if was_recording:
                self._close_file()
            self.fps = new_fps
            if was_recording:
                self._start_new_file()
