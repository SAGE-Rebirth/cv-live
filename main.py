from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import argparse
import os
import sys
import signal
import shutil
import threading
from dotenv import load_dotenv
import logging

from src.config import Config
from src.logging_setup import setup_logging

setup_logging("API")
logger = logging.getLogger(__name__)

from src.service import CameraService

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

# Lazy service init — MUST NOT construct CameraService at module level.
# With 'spawn' multiprocessing (default on macOS), child processes
# re-import __main__ which would create a second CameraService, destroying
# the parent's shared memory segment and producing blank recordings.
camera_service: CameraService | None = None


def get_service() -> CameraService:
    """Return the live CameraService. Only valid after lifespan startup."""
    assert camera_service is not None, "Service not started yet"
    return camera_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global camera_service
    camera_service = CameraService(bucket_name=BUCKET_NAME)
    camera_service.start()
    try:
        yield
    finally:
        camera_service.stop()
        camera_service = None


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
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Pydantic Models ---
class StatusResponse(BaseModel):
    recording: bool = Field(..., description="True if the system is currently recording video to disk.")
    gesture_enabled: bool = Field(..., description="True if gesture control is active.")

class ActionResponse(BaseModel):
    status: str = Field(..., description="Confirmation message of the action taken.")

class MetricsResponse(BaseModel):
    recording: bool = Field(..., description="Recording status.")
    disk_usage_percent: float = Field(..., description="Percentage of disk space used.")
    disk_free_gb: float = Field(..., description="Free disk space in Gigabytes.")
    fps_configured: int = Field(..., description="Target FPS configuration.")

# --- Endpoints ---

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    """
    Serves the Web Dashboard.
    """
    return templates.TemplateResponse(request, "index.html")

@app.get("/api/status", response_model=StatusResponse, tags=["Monitoring"])
def get_status():
    """
    Get the current recording state.
    """
    return get_service().get_status()

@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
def get_metrics():
    """
    Get detailed system metrics including disk usage and storage stats.
    Useful for health checks.
    """
    total, used, free = shutil.disk_usage(".")
    return {
        "recording": get_service().get_status()["recording"],
        "disk_usage_percent": round((used / total) * 100, 1),
        "disk_free_gb": round(free / (1024**3), 2),
        "fps_configured": Config.FPS,
    }

@app.post("/api/start", response_model=ActionResponse, tags=["Control"])
def start_recording():
    """
    Manually start recording.
    Equivalent to showing the 'Peace Sign' gesture.
    """
    logger.info("API: Received manual Start request.")
    get_service().toggle_recording(True)
    return {"status": "started"}

@app.post("/api/stop", response_model=ActionResponse, tags=["Control"])
def stop_recording():
    """
    Manually stop recording.
    Equivalent to showing the 'Open Palm' gesture.
    Triggers upload of the current segment.
    """
    logger.info("API: Received manual Stop request.")
    get_service().toggle_recording(False)
    return {"status": "stopped"}

@app.post("/api/gesture-toggle", response_model=ActionResponse, tags=["Control"])
def toggle_gesture():
    """
    Toggle gesture control on/off. When disabled, only manual buttons,
    terminal commands, and API calls can start/stop recording.
    """
    svc = get_service()
    svc.set_gesture_enabled(not svc.gesture_enabled)
    state = "enabled" if svc.gesture_enabled else "disabled"
    return {"status": f"gestures {state}"}


@app.post("/api/quit", response_model=ActionResponse, tags=["Control"])
def quit_server():
    """
    Gracefully shut down the entire application.
    Stops recording, cleans up processes, then terminates the server.
    """
    logger.info("API: Received quit request.")
    # Send SIGINT to ourselves after a short delay so we can return the
    # response to the client before the server stops.
    def _delayed_shutdown():
        import time as _time
        _time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)
    threading.Thread(target=_delayed_shutdown, daemon=True).start()
    return {"status": "shutting down"}


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
    Writes to settings.yaml. Validation is delegated to the pydantic
    runtime-settings model.
    """
    # Cast to int if it looks like one (YAML prefers ints)
    val = update.value
    if val.is_integer():
        val = int(val)

    try:
        Config.update_setting(update.key, val)
    except (ValueError, Exception) as e:  # pydantic ValidationError subclasses Exception
        return JSONResponse(status_code=400, content={"error": str(e)})

    # Push the change into the live pipeline (reopens camera for FPS, etc.)
    get_service().apply_runtime_change(update.key, val)

    return {"status": "updated", "key": update.key, "value": val}

def gen_frames():
    """Generator for the MJPEG video stream.

    Blocks on the service's frame_condition so we never spin and so each
    viewer wakes within microseconds of a fresh frame. The generator exits
    cleanly when the service stops or the client disconnects (StreamingResponse
    swallows the GeneratorExit raised on disconnect).
    """
    svc = get_service()
    last_sent = None
    while svc.running:
        with svc.frame_condition:
            # Wait until a *new* frame is available (or 1s timeout to re-check shutdown)
            svc.frame_condition.wait_for(
                lambda: svc.current_frame is not last_sent
                or not svc.running,
                timeout=1.0,
            )
            frame = svc.current_frame

        if frame is None or frame is last_sent:
            continue
        last_sent = frame
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.get("/video_feed", tags=["Stream"])
def video_feed():
    """
    Stream the live camera feed in MJPEG format.
    Can be embedded in an <img> tag.
    """
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------------------
# CLI: argument parser + terminal control loop
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="CV Live — gesture-controlled video recording system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Terminal commands (always available while the server is running):
  r   Start recording
  s   Stop recording
  g   Toggle gesture control on/off
  q   Quit (clean shutdown)

Examples:
  python3 main.py                      # default: web dashboard on port 8000
  python3 main.py --headless           # no browser, terminal-only
  python3 main.py --port 9000          # custom port
  python3 main.py --headless --port 80 # headless on port 80
""",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without opening a browser. Control via terminal commands (r/s/q).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    return parser.parse_args()


def _terminal_loop(server_shutdown_event):
    """Read single-key commands from stdin.

    Runs in a daemon thread so it doesn't block shutdown.  On headless
    Raspberry Pis this is the primary control interface.
    """
    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    print("\n--- CV Live Terminal Controls ---")
    print("  r = start recording")
    print("  s = stop recording")
    print("  g = toggle gesture control")
    print("  q = quit")
    print("--------------------------------\n")

    try:
        tty.setcbreak(fd)  # single-char reads, no echo
        while not server_shutdown_event.is_set():
            # Use select so we can check the shutdown event periodically
            import select
            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not ready:
                continue
            ch = sys.stdin.read(1).lower()
            if ch == "r":
                get_service().toggle_recording(True)
                print("[terminal] Recording STARTED")
            elif ch == "s":
                get_service().toggle_recording(False)
                print("[terminal] Recording STOPPED")
            elif ch == "g":
                svc = get_service()
                svc.set_gesture_enabled(not svc.gesture_enabled)
                state = "ON" if svc.gesture_enabled else "OFF"
                print(f"[terminal] Gesture control {state}")
            elif ch == "q":
                print("[terminal] Shutting down...")
                server_shutdown_event.set()
                # Send SIGINT to ourselves to stop uvicorn's event loop
                os.kill(os.getpid(), signal.SIGINT)
                return
    except (EOFError, OSError):
        # stdin closed (e.g. running as systemd service with no tty)
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


if __name__ == "__main__":
    import uvicorn

    args = _parse_args()

    shutdown_event = threading.Event()

    # Start terminal control thread (works in both headless and normal mode)
    if sys.stdin.isatty():
        terminal_thread = threading.Thread(
            target=_terminal_loop, args=(shutdown_event,), daemon=True
        )
        terminal_thread.start()

    if not args.headless:
        print(f"Dashboard: http://localhost:{args.port}")
        print(f"API docs:  http://localhost:{args.port}/docs")
    else:
        print(f"Headless mode. API at http://localhost:{args.port}")
        print("Use terminal commands (r/s/q) or the API to control recording.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
