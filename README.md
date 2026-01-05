# CV Live - Intelligent Gesture Recorded Camera System

**CV Live** is a high-performance computer vision application designed for Raspberry Pi 5. It intelligently records video segments based on hand gestures, optimizes storage using advanced compression, and automatically uploads footage to AWS S3. It also features a web-based dashboard for remote monitoring and control.

## Table of Contents
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Endpoints](#api-endpoints)
- [Deployment (Auto-Start)](#deployment-auto-start)
- [Architecture & Optimization](#architecture--optimization)
- [Dos and Donts](#dos-and-donts)

## Features
- **Gesture Control**: Start recording with a "Two Finger" (Peace) sign, stop with a "Five Finger" (Open Palm) sign.
- **Auto-Segmentation**: Longer recordings are automatically split into 5-minute segments.
- **Optimized Storage**: Uses FFmpeg with H.264 compression (CRF) to reduce file sizes by ~90% compared to standard raw capture.
- **Cloud Integration**: Automatically uploads completed segments to AWS S3 in the background.
- **Resiliency**:
    - **Disk Watchdog**: Prevents recording if disk usage exceeds 85%.
    - **Ring Buffer Storage**: Automatically deletes the oldest video file when disk is full, ensuring continuous operation.
    - **Thermal Protection**: Monitors CPU temperature and automatically minimizes AI usage if the device overheats (>75°C).
    - **Auto-Cleanup & Retry**: Quarantine logic for failed uploads.
- **Web Dashboard**: View live feed and control the system from any browser on the network.
- **Performance**:
    - **Multi-Processing Architecture**: Uses separate CPU cores for Camera Capture, AI Inference, and Video Recording to ensure smooth 30FPS performance.
    - **Zero-Copy buffers**: specialized shared memory for max speed.

## Prerequisites
- **Hardware**: Raspberry Pi 5 (Preferred) or Mac/PC with Webcam.
- **System**: Raspberry Pi OS (Bookworm) or macOS.
- **Dependencies**:
    - Python 3.9+
    - FFmpeg (`sudo apt install ffmpeg` or `brew install ffmpeg`)
    - AWS Account (S3 Bucket)

## Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yourusername/cv-live.git
    cd cv-live
    ```

2.  **Create Virtual Environment**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Python Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Install FFmpeg**
    *   **Raspberry Pi / Linux**:
        ```bash
        sudo apt update && sudo apt install ffmpeg
        ```
    *   **Mac**:
        ```bash
        brew install ffmpeg
        ```

## Configuration (Beginner Friendly Guide)

This project uses a `.env` file to manage all settings. This makes it easy to change settings without touching the code.

### Step 1: Create the Config File
In the project folder, create a new file named `.env`. You can do this by running:
```bash
nano .env
```
Then copy-paste the following configuration into it.

### Step 2: The Configuration Variables
Here is exactly what you need to put in that file.

#### 1. AWS Cloud Settings (Required)
These allow the system to upload videos to your cloud bucket.
```ini
S3_BUCKET_NAME=my-cv-bucket-name
S3_REGION=us-east-1
# If you have AWS CLI installed, you don't need the keys below.
# If not, uncomment and add your IAM User keys:
# AWS_ACCESS_KEY_ID=AKIA......
# AWS_SECRET_ACCESS_KEY=SumSecreTKeY.....
```

#### 2. Camera Settings
Adjust these if you use a different specific camera.
```ini
CAMERA_INDEX=0       # 0 is usually the default USB webcam or Pi Cam. Try 1 if 0 fails.
FRAME_WIDTH=640      # Logical recording width.
FRAME_HEIGHT=480     # Logical recording height.
FPS=30               # Target Frames Per Second.
```

#### 3. Storage & Safety (Important)
Control how files are saved and when to delete old ones.
```ini
RECORDINGS_DIR=recordings        # Folder where videos are saved locally.
RECORDING_SEGMENT_DURATION=300   # (Seconds) Split video into new file every 5 mins.
MAX_DISK_USAGE_PERCENT=85        # If Disk is > 85% full, delete oldest file.
RETENTION_COUNT=100              # Keep max 100 files locally before deleting.
```

#### 4. Performance Tuning
Tweak these if the system feels slow or hot.
```ini
# MODEL_COMPLEXITY:
# Set to 0 for Raspberry Pi (Faster).
# Set to 1 for Mac/PC (More Accurate).
MODEL_COMPLEXITY=0

# DETECTION_RATE:
# Run AI check every N frames.
# 1 = Check every frame (Max CPU usage).
# 5 = Check every 5th frame (Recommended for Pi).
DETECTION_RATE=5
```

#### 5. Debugging
```ini
LOG_LEVEL=INFO   # INFO is standard. Use DEBUG for more details.
```

## Usage

Start the application manually:
```bash
python3 main.py
```

### Gestures
*   **Start Recording**: Show **Index + Middle Fingers** (Peace Sign).
*   **Stop Recording**: Show **Open Palm** (5 Fingers).

### Web Dashboard
Open your browser and navigate to:
*   `http://localhost:8000` (Local)
*   `http://<PI_IP_ADDRESS>:8000` (Remote)

## API Endpoints
The application exposes a fully documented REST API.
For detailed documentation, see [API.md](API.md) or visit `/docs` in your browser when the app is running.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/status` | Current recording status |
| `GET` | `/metrics` | System telemetry |
| `POST` | `/api/start` | Start recording |
| `POST` | `/api/stop` | Stop recording |
| `GET` | `/video_feed` | Live video stream |
| `GET` | `/docs` | **Interactive Swagger UI Documentation** |
| `GET` | `/redoc` | ReDoc API Reference |

### API Usage Examples

**1. Access Documentation**
*   Open your browser to: `http://<YOUR_PI_IP>:8000/docs`
*   You will see an interactive dashboard to test every button.

**2. Check Status (Command Line)**
```bash
curl http://localhost:8000/api/status
# Output: {"recording": false}
```

**3. Start Recording**
```bash
curl -X POST http://localhost:8000/api/start
# Output: {"status": "started"}
```

**4. Stop Recording**
```bash
curl -X POST http://localhost:8000/api/stop
# Output: {"status": "stopped"}
```

## Deployment (Auto-Start)
To run this application as a background service on Raspberry Pi:

1.  **Edit Service File**:
    Modify `cv-live.service`. Update `User` and `WorkingDirectory` paths to match your location.

2.  **Install Services**:
    ```bash
    sudo cp cv-live.service /etc/systemd/system/
    sudo cp cv-uploader.service /etc/systemd/system/
    sudo systemctl daemon-reload
    ```

3.  **Enable & Start Services**:
    ```bash
    # Camera Service
    sudo systemctl enable cv-live
    sudo systemctl start cv-live
    
    # Upload Watcher Service
    sudo systemctl enable cv-uploader
    sudo systemctl start cv-uploader
    ```

4.  **Monitor Logs**:
    ```bash
    # Camera Logs
    journalctl -u cv-live -f
    
    # Uploader Logs
    journalctl -u cv-uploader -f
    ```

## Architecture & Optimization
*   **src/main.py**: FastAPI Server entry point.
*   **src/service.py**: Central orchestrator. Runs a loop that reads from `ThreadedCamera`, skips N frames (`DETECTION_RATE`), runs `GestureDetector`, and pipes frames to `FFmpegRecorder`.
*   **src/ffmpeg_recorder.py**: Spawns an `ffmpeg` subprocess. Writes raw video frames to `stdin` using a separate thread/queue to prevent blocking.
*   **src/storage.py**: Background thread manager for S3 uploads. Handles retries and local disk cleanup.

## Dos and Donts

### DO
*   **Do** ensure FFmpeg is installed before running.
*   **Do** set `MODEL_COMPLEXITY=0` on Raspberry Pi for best performance.
*   **Do** use a fast SD card or external SSD on the Pi for reliable recording.
*   **Do** test the S3 credentials using `aws s3 ls` or similar before deployment.

### DON'T
*   **Don't** set resolution to 4K on the Pi; 640x480 or 720p is recommended for ML tasks.
*   **Don't** block the main thread. All I/O (Disk, Network) is already threaded for you.
*   **Don't** delete the `.env` file without setting environment variables elsewhere.
