import cv2
import threading
import time
import os
import logging
from src.gesture import GestureDetector
from src.ffmpeg_recorder import FFmpegRecorder
from src.storage import S3Uploader
from src.config import Config
from src.camera import ThreadedCamera

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CameraService:
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.running = False
        self.thread = None
        
        # Components
        self.uploader = S3Uploader(bucket_name=self.bucket_name)
        self.recorder = FFmpegRecorder(
            output_dir=Config.RECORDINGS_DIR,
            width=Config.FRAME_WIDTH,
            height=Config.FRAME_HEIGHT,
            fps=Config.FPS
        )
        self.detector = GestureDetector() 
        self.camera = None
        
        # State
        
        # Multi-Processing Components
        self.shared_state = SharedStateManager()
        self.result_queue = multiprocessing.Queue(maxsize=10)
        
        self.capture_process = CaptureProcess(self.shared_state, camera_index)
        self.inference_process = InferenceProcess(self.shared_state, self.result_queue)
        
        self.processing_thread = None

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

    def stop(self):
        logger.info("Stopping components...")
        self.running = False
        self.shared_state.running_flag.value = False
        
        if self.recorder.is_recording:
            self.recorder.stop_recording()
            
        self.processing_thread.join()
        self.capture_process.join()
        self.inference_process.join()
        self.shared_state.cleanup()
        logger.info("Service Stopped.")

    def _main_loop(self):
        last_gesture = None
        
        while self.running:
            # 1. Get Frame from Shared Memory
            try:
                frame = self.shared_state.get_frame()
            except Exception:
                 time.sleep(0.01)
                 continue

            # 2. Check for Inference Results
            try:
                while not self.result_queue.empty():
                    gesture = self.result_queue.get_nowait()
                    if gesture:
                        last_gesture = gesture
                        self._handle_gesture_logic(gesture)
            except queue.Empty:
                pass
            
            # 3. Draw Overlay (In main process for display)
            # Make a copy for UI encoding to keep it safe? Or just use it.
            # MJPEG needs bytes.
            
            # Visual Feedback
            cv2.putText(frame, f"REC: {self.recorder.is_recording}", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if self.recorder.is_recording else (0, 255, 0), 2)
            if last_gesture:
                cv2.putText(frame,f"Gesture: {last_gesture}",(10,60),cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

            # 4. Pipe to Recorder
            if self.recorder.is_recording:
                self.recorder.write_frame(frame)

            # 5. Update JPEG for Web Stream
            ret, buffer = cv2.imencode('.jpg', frame)
            if ret:
                with self.lock:
                    self.current_frame = buffer.tobytes()
