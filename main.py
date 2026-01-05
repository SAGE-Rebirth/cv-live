from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import os
import time
import shutil
from dotenv import load_dotenv
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [API] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from src.service import CameraService
from src.config import Config

load_dotenv()
BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "my-cv-bucket")

# Metadata for Docs
tags_metadata = [
    {
        "name": "Control",
        "description": "Operations to start/stop recording.",
    },
    {
        "name": "Monitoring",
        "description": "Check system status and hardware metrics.",
    },
    {
        "name": "Stream",
        "description": "Live video feed.",
    },
]

app = FastAPI(
    title="CV Live System API",
    description="""
    Control interface for the Intelligent Gesture Camera System.
    
    ## Features
    * **Start/Stop Recording**: Manual control overrides.
    * **Live Stream**: Low-latency MJPEG feed.
    * **Metrics**: Real-time disk and system health monitoring.
    """,
    version="1.0.0",
    openapi_tags=tags_metadata
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Global Service
camera_service = CameraService(bucket_name=BUCKET_NAME)

# --- Pydantic Models ---
class StatusResponse(BaseModel):
    recording: bool = Field(..., description="True if the system is currently recording video to disk.")

class ActionResponse(BaseModel):
    status: str = Field(..., description="Confirmation message of the action taken.")

class MetricsResponse(BaseModel):
    recording: bool = Field(..., description="Recording status.")
    disk_usage_percent: float = Field(..., description="Percentage of disk space used.")
    disk_free_gb: float = Field(..., description="Free disk space in Gigabytes.")
    fps_configured: int = Field(..., description="Target FPS configuration.")

# --- Lifecycle ---
@app.on_event("startup")
def startup_event():
    camera_service.start()

@app.on_event("shutdown")
def shutdown_event():
    camera_service.stop()

# --- Endpoints ---

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    """
    Serves the Web Dashboard.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/status", response_model=StatusResponse, tags=["Monitoring"])
def get_status():
    """
    Get the current recording state.
    """
    return camera_service.get_status()

@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
def get_metrics():
    """
    Get detailed system metrics including disk usage and storage stats.
    Useful for health checks.
    """
    total, used, free = shutil.disk_usage(".")
    return {
        "recording": camera_service.get_status()["recording"],
        "disk_usage_percent": round((used / total) * 100, 1),
        "disk_free_gb": round(free / (1024**3), 2),
        "fps_configured": camera_service.recorder.fps
    }

@app.post("/api/start", response_model=ActionResponse, tags=["Control"])
def start_recording():
    """
    Manually start recording. 
    Equivalent to showing the 'Peace Sign' gesture.
    """
    logger.info("API: Received manual Start request.")
    camera_service.toggle_recording(True)
    return {"status": "started"}

@app.post("/api/stop", response_model=ActionResponse, tags=["Control"])
def stop_recording():
    """
    Manually stop recording.
    Equivalent to showing the 'Open Palm' gesture. 
    Triggers upload of the current segment.
    """
    logger.info("API: Received manual Stop request.")
    camera_service.toggle_recording(False)
    return {"status": "stopped"}

@app.get("/api/config", tags=["Configuration"])
def get_config():
    """
    Get all current configuration settings (Static + Dynamic).
    """
    return Config.get_all()

class ConfigUpdate(BaseModel):
    key: str
    value: float # Union[int, float] simplified

@app.post("/api/config", tags=["Configuration"])
def update_config(update: ConfigUpdate):
    """
    Update a dynamic setting (e.g. DETECTION_RATE).
    Writes to settings.yaml.
    """
    # Allowed keys verification
    ALLOWED = ["DETECTION_RATE", "MODEL_COMPLEXITY", "RECORDING_SEGMENT_DURATION", 
               "MAX_DISK_USAGE_PERCENT", "RETENTION_COUNT"]
    
    if update.key not in ALLOWED:
        return JSONResponse(status_code=400, content={"error": f"Key {update.key} is not editable or invalid."})

    # Cast to int if it looks like one (YAML prefers ints)
    val = update.value
    if val.is_integer():
        val = int(val)
        
    Config.update_setting(update.key, val)
    return {"status": "updated", "key": update.key, "value": val}

def gen_frames():
    """Generator for video streaming"""
    while True:
        with camera_service.lock:
            frame = camera_service.current_frame
        
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            time.sleep(0.1)

@app.get("/video_feed", tags=["Stream"])
def video_feed():
    """
    Stream the live camera feed in MJPEG format.
    Can be embedded in an <img> tag.
    """
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
