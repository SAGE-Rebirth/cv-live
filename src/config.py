import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Camera Settings
    CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", 0))
    FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", 640))
    FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", 480))
    FPS = int(os.getenv("FPS", 30))
    
    # Recording Settings
    RECORDING_SEGMENT_DURATION = int(os.getenv("RECORDING_SEGMENT_DURATION", 300)) # 5 mins
    RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "recordings")
    
    # Safety & Storage
    # Safety & Storage
    MAX_DISK_USAGE_PERCENT = int(os.getenv("MAX_DISK_USAGE_PERCENT", 85))
    RETENTION_COUNT = int(os.getenv("RETENTION_COUNT", 100))
    
    # AI Settings
    MODEL_COMPLEXITY = int(os.getenv("MODEL_COMPLEXITY", 0))
    MIN_DETECTION_CONFIDENCE = 0.5
    MIN_TRACKING_CONFIDENCE = 0.5
    DETECTION_RATE = int(os.getenv("DETECTION_RATE", 5)) # Run AI every N frames
    
    # AWS Settings
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "my-cv-bucket")
    S3_REGION = os.getenv("S3_REGION", "us-east-1")
    UPLOAD_MAX_RETRIES = 3
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
