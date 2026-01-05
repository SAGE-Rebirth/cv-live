import os
import yaml
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.yaml")

class ConfigMeta(type):
    """
    Metaclass to allow Config.KEY access to be dynamic for settings.yaml values,
    while keeping static values static.
    """
    _settings = {}
    _last_load_time = 0

    def __getattr__(cls, name):
        # 1. Check if it's a known dynamic setting
        # If the class hasn't loaded settings yet, load them.
        if not cls._settings:
            cls.load_settings()
        
        if name in cls._settings:
            return cls._settings[name]
        
        # 2. Fallback to what was defined in the class (Static)
        # (This path is usually handled by Python's normal attribute lookup before __getattr__)
        raise AttributeError(f"Config has no attribute '{name}'")

    def load_settings(cls):
        """Reloads settings from YAML."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    cls._settings = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Failed to load settings.yaml: {e}")
        else:
            logger.warning("settings.yaml not found! Using empty defaults.")
            cls._settings = {}

    def update_setting(cls, key, value):
        """Updates a setting and writes to YAML."""
        cls._settings[key] = value
        try:
            with open(SETTINGS_FILE, 'w') as f:
                yaml.dump(cls._settings, f)
            logger.info(f"Updated setting {key} = {value}")
        except Exception as e:
            logger.error(f"Failed to save settings.yaml: {e}")

    def get_all(cls):
        """Returns all config (Static + Dynamic) for API."""
        # Start with static env vars we care about
        data = {
           "CAMERA_INDEX": cls.CAMERA_INDEX,
           "FRAME_WIDTH": cls.FRAME_WIDTH,
           "FRAME_HEIGHT": cls.FRAME_HEIGHT,
           "FPS": cls.FPS,
           "S3_BUCKET_NAME": cls.S3_BUCKET_NAME,
           "LOG_LEVEL": cls.LOG_LEVEL,
           "RECORDINGS_DIR": cls.RECORDINGS_DIR
        }
        # Merge Dynamic
        data.update(cls._settings)
        return data

class Config(metaclass=ConfigMeta):
    # --- Static / Env Vars (Requires Restart) ---
    
    # Camera
    CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", 0))
    FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", 640))
    FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", 480))
    FPS = int(os.getenv("FPS", 30))
    
    # Cloud
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "my-cv-bucket")
    S3_REGION = os.getenv("S3_REGION", "us-east-1")
    UPLOAD_MAX_RETRIES = 3
    
    # Infra
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "recordings")

    # --- Dynamic Settings (Managed by Metaclass via settings.yaml) ---
    # These types are here for IDE hints / fallback if needed, but __getattr__ overrides if in yaml.
    # We don't define them here to force lookup, OR we define defaults.
    # Let's rely on __getattr__ so we know it's dynamic.
    
    # DETECTION_RATE
    # MODEL_COMPLEXITY
    # RECORDING_SEGMENT_DURATION
    # MAX_DISK_USAGE_PERCENT
    # RETENTION_COUNT
