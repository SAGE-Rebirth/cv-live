# CV Live — Gesture-Controlled Camera Recorder

**CV Live** is a smart camera recorder that watches your hand gestures and starts/stops video recording on its own. It's designed to run continuously on a Raspberry Pi 5 (or any Mac/PC with a webcam) and can optionally upload finished recordings to AWS S3 — but it works perfectly fine without any cloud setup at all.

You can also control it from a web dashboard in your browser, on the same Wi-Fi network as the device.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [How It Works (Big Picture)](#how-it-works-big-picture)
3. [What You Need](#what-you-need)
4. [Installation (Step by Step)](#installation-step-by-step)
5. [Configuration](#configuration)
6. [Running the App](#running-the-app)
7. [Using the Web Dashboard](#using-the-web-dashboard)
8. [Gestures](#gestures)
9. [Local Mode vs Cloud Mode](#local-mode-vs-cloud-mode)
10. [API Reference](#api-reference)
11. [Running on a Raspberry Pi (Auto-Start)](#running-on-a-raspberry-pi-auto-start)
12. [Project Structure](#project-structure)
13. [Architecture & Performance](#architecture--performance)
14. [Running the Tests](#running-the-tests)
15. [Troubleshooting](#troubleshooting)
16. [Tips, Dos & Don'ts](#tips-dos--donts)

---

## What It Does

- **Watches your camera** continuously using a hand-tracking AI model (Google MediaPipe).
- **Detects two hand gestures**:
  - ✌️ **Peace sign** (index + middle finger up) → starts recording
  - 🖐️ **Open palm** (all five fingers up) → stops recording
- **Records video** to your local disk as `.mp4` files, automatically split into 5-minute chunks.
- **Uploads each chunk to AWS S3** in the background, *if* you give it AWS credentials. If you don't, it just keeps the files locally.
- **Manages disk space** automatically — when the disk gets full, it deletes the oldest recording first so it can keep going forever without manual intervention.
- **Provides a web dashboard** so you can watch the live feed and tweak settings from any phone or computer on the network.
- **Survives crashes** — the recorder and the uploader run as two separate background services, so a problem in one doesn't take down the other.

---

## How It Works (Big Picture)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Camera      │───▶│  Hand AI     │───▶│  Debouncer   │
│  (capture)   │    │  (inference) │    │  (10s hold)  │
└──────┬───────┘    └──────────────┘    └──────┬───────┘
       │                                        │
       ▼                                        ▼
┌──────────────┐                         ┌──────────────┐
│  Video       │                         │  Recorder    │
│  Recorder    │◀────── start/stop ──────│  on/off      │
│  (.mp4)      │                         └──────────────┘
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌──────────────┐
│  Local       │───▶│  Upload      │ (only if AWS creds set;
│  recordings/ │    │  Watcher     │  otherwise just keeps
└──────────────┘    │  → S3        │  files locally)
                    └──────────────┘
```

The system uses **three CPU cores in parallel** so the camera, the AI, and the recording never block each other — that's how it stays smooth at 30 FPS on a Raspberry Pi.

---

## What You Need

### Hardware
- **Raspberry Pi 5** (recommended), OR
- A **Mac / Linux PC** with a USB webcam (great for development and testing)

### Software
- **Python 3.9 or newer**
- **A working webcam** (built-in or USB)
- *(Optional)* An **AWS account with an S3 bucket**, if you want cloud upload

### What you DON'T need
- ❌ AWS credentials — the system runs in local-only mode if you skip them
- ❌ FFmpeg — the recorder uses OpenCV's built-in video writer
- ❌ A GPU — MediaPipe runs on the CPU

---

## Installation (Step by Step)

These instructions assume you've never set up a Python project before. If you're an experienced developer, you can probably skim.

### 1. Get the code

Open a terminal and run:

```bash
git clone https://github.com/SAGE-Rebirth/cv-live.git
cd cv-live
```

You should now be inside the `cv-live` folder. Run `ls` to confirm — you should see files like `main.py`, `requirements.txt`, etc.

### 2. Create an isolated Python environment

This step keeps the project's libraries separate from your system Python so nothing breaks elsewhere on your machine.

```bash
python3 -m venv .venv
```

Then **activate** it:

- **On Mac/Linux:**
  ```bash
  source .venv/bin/activate
  ```
- **On Windows:**
  ```cmd
  .venv\Scripts\activate
  ```

After activation, your terminal prompt should show `(.venv)` at the start. You're now "inside" the isolated environment.

### 3. Install the Python libraries

```bash
pip install -r requirements.txt
```

This will download and install everything: OpenCV, MediaPipe, FastAPI, boto3, and so on. It can take a few minutes the first time.

### 4. Download the AI model

The app needs a small AI model file to recognize hand landmarks. It's about 8 MB.

```bash
mkdir -p src/models
curl -L https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task \
  -o src/models/hand_landmarker.task
```

If `curl` isn't available, you can paste that URL into a browser and save the downloaded file as `src/models/hand_landmarker.task`.

### 5. (Optional) Create a `.env` file

Only do this if you want to change defaults or use AWS S3. See the [Configuration](#configuration) section below for what to put in it. **You can totally skip this step** and the app will run with sensible defaults in local-only mode.

---

## Configuration

CV Live has two layers of settings:

| Layer | Where it lives | When it changes | What it controls |
|---|---|---|---|
| **Static** | `.env` file (or environment variables) | Requires app restart | Camera index, resolution, S3 credentials, log level |
| **Runtime** | `settings.yaml` | Live, via the web dashboard | Detection rate, segment length, disk limit, retention |

You don't *need* to create either file — both have safe defaults baked in.

### The `.env` file (static settings)

Create a file named `.env` in the project folder. Here's a complete annotated example — copy it and only uncomment what you actually want to change:

```ini
# ========== Camera ==========
# Which camera to use. 0 is usually the default webcam. Try 1 if 0 fails.
CAMERA_INDEX=0
FRAME_WIDTH=640
FRAME_HEIGHT=480
FPS=30

# ========== AWS S3 (Optional) ==========
# Leave S3_BUCKET_NAME empty (or remove these lines) to run in LOCAL MODE.
# If you set a bucket but credentials don't work, the app falls back to
# local mode automatically and tells you why in the logs.
# S3_BUCKET_NAME=my-cv-bucket-name
# S3_REGION=us-east-1

# If you've already set up the AWS CLI (`aws configure`), you do NOT need
# the keys below — boto3 will pick them up automatically. Only set these
# if you have IAM user keys you want to use directly:
# AWS_ACCESS_KEY_ID=AKIA......
# AWS_SECRET_ACCESS_KEY=SumSecreTKeY.....

# ========== Storage Paths ==========
RECORDINGS_DIR=recordings
LOGS_DIR=logs

# ========== Gesture Behavior ==========
# How long (in seconds) the user must hold a gesture before it triggers.
# Lower = faster response but more accidental triggers.
GESTURE_CONFIRMATION_SECONDS=10

# ========== Logging ==========
LOG_LEVEL=INFO
```

### The `settings.yaml` file (runtime settings)

These can be edited live from the web dashboard, but you can also edit the file directly. Defaults look like this:

```yaml
# How often the AI runs. 1 = every frame (max CPU). 5 = every 5th frame
# (recommended on Raspberry Pi). Higher = less CPU.
DETECTION_RATE: 5

# 0 = lighter model (recommended on Pi). 1 = heavier, more accurate.
MODEL_COMPLEXITY: 0

# How long each video chunk is, in seconds. 300 = 5 minutes.
RECORDING_SEGMENT_DURATION: 300

# When the disk is more than this percent full, delete the oldest recording.
MAX_DISK_USAGE_PERCENT: 85

# Maximum number of .mp4 files to keep locally.
RETENTION_COUNT: 100
```

All values are validated when you save them — bad inputs (like a negative `DETECTION_RATE`) are rejected.

---

## Running the App

Make sure your virtual environment is active (`source .venv/bin/activate`), then:

### Standard mode

```bash
python3 main.py
```

You should see something like:

```text
INFO:     Started server process [1234]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Development mode (auto-reload on file changes)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

To stop the app, press **Ctrl+C** in the terminal.

---

## Using the Web Dashboard

Open a browser and go to:

- **From the same machine**: `http://localhost:8000`
- **From another device on the same network**: `http://<your-device-ip>:8000`

You'll see:

- A **live video feed** showing what the camera sees, with overlays.
- A **status badge** (IDLE / RECORDING).
- **Telemetry**: configured FPS, resolution, disk usage.
- **Manual control buttons**: Start Recording / Stop Recording.
- A **⚙️ Settings** button that opens a modal where you can tweak the runtime config (detection rate, segment duration, disk limit) and save it without restarting.

To find your device's IP address:

- **Mac**: `ipconfig getifaddr en0`
- **Linux/Pi**: `hostname -I`
- **Windows**: `ipconfig`

---

## Gestures

When the camera sees your hand, it'll show a small overlay on the video feed with the gesture name and a progress bar.

| Gesture | Action |
|---|---|
| ✌️ **Peace sign** (index + middle finger up, others down) | Start recording |
| 🖐️ **Open palm** (all five fingers up) | Stop recording |

You must **hold the gesture steady** for the configured number of seconds (default 10s — you can change this with `GESTURE_CONFIRMATION_SECONDS`). This prevents accidental triggers from random hand movements.

The dashboard overlay will count up `0% → 100%` so you know how long is left. When it hits **CONFIRMED**, the action fires.

After it fires, you have to lower your hand (or change the gesture) before the same one can fire again — the system doesn't spam-toggle while you keep holding.

---

## Local Mode vs Cloud Mode

CV Live is designed so that **AWS is completely optional**. There are two modes, and the system picks one automatically:

### LOCAL MODE (default if no S3 setup)

- All recordings stay on the device's local disk in the `recordings/` folder.
- When the disk fills past `MAX_DISK_USAGE_PERCENT` (or you exceed `RETENTION_COUNT` files), the **oldest** file is deleted first to make room.
- Nothing ever goes to the cloud. No AWS account or credentials required.

### CLOUD MODE (if S3 setup is valid)

- The system runs the recorder normally; the uploader watches the `recordings/` folder.
- When a recording chunk finishes, it gets uploaded to your S3 bucket and the local copy is deleted.
- If an upload fails 3 times in a row, the file is moved to a `quarantine/` folder (outside `recordings/`) so it doesn't keep retrying forever.

### How does it decide which mode?

When the app starts, the uploader checks all of the following:

1. Is `S3_BUCKET_NAME` set?
2. Can boto3 find AWS credentials (env vars, AWS CLI profile, or IAM role)?
3. Does `head_bucket` succeed against the bucket? (verifies the credentials can actually access it)

**If all three pass → CLOUD MODE.** Otherwise → LOCAL MODE, and the logs will tell you exactly why so you can fix it. For example:

```
S3 disabled: bucket 'my-bucket' is configured but no AWS credentials could be resolved. Running in LOCAL MODE.
```

This means you can develop locally without AWS, then add credentials later and the same code switches to cloud mode automatically.

---

## API Reference

The full Swagger UI is available at `http://<device-ip>:8000/docs` when the app is running. Here's the short version:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web dashboard |
| `GET` | `/api/status` | `{"recording": true/false}` |
| `GET` | `/metrics` | Disk usage, free space, FPS |
| `POST` | `/api/start` | Start recording manually |
| `POST` | `/api/stop` | Stop recording manually |
| `GET` | `/api/config` | All current settings |
| `POST` | `/api/config` | Update one runtime setting |
| `GET` | `/video_feed` | MJPEG live stream (use in `<img>` tags) |
| `GET` | `/docs` | Interactive Swagger documentation |

### Quick examples

```bash
# Check status
curl http://localhost:8000/api/status
# → {"recording": false}

# Start recording
curl -X POST http://localhost:8000/api/start
# → {"status": "started"}

# Stop recording
curl -X POST http://localhost:8000/api/stop
# → {"status": "stopped"}

# Change a runtime setting
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"key": "DETECTION_RATE", "value": 3}'
```

For full request/response details, see [API.md](API.md) or the Swagger UI.

---

## Running on a Raspberry Pi (Auto-Start)

For production use on a Pi, you'll want the app to start automatically on boot and restart itself if it crashes. CV Live ships with two `systemd` service files for this:

- `cv-live.service` — runs the camera/web app (`main.py`)
- `cv-uploader.service` — runs the upload watcher (`upload_watcher.py`)

These are deliberately separate so a crash in the camera service doesn't lose pending uploads, and vice versa.

### Install the services

1. **Edit the service files** to match your username and folder:
   ```bash
   nano cv-live.service
   nano cv-uploader.service
   ```
   Update the `User=` and `WorkingDirectory=` lines.

2. **Copy them into the system folder and reload:**
   ```bash
   sudo cp cv-live.service cv-uploader.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

3. **Enable + start both services:**
   ```bash
   sudo systemctl enable cv-live cv-uploader
   sudo systemctl start cv-live cv-uploader
   ```

4. **Check that everything is running:**
   ```bash
   sudo systemctl status cv-live
   sudo systemctl status cv-uploader
   ```

5. **Watch the live logs:**
   ```bash
   journalctl -u cv-live -f
   journalctl -u cv-uploader -f
   ```

For a deeper explanation of the service files and systemd commands, see [SERVICE.md](SERVICE.md).

---

## Project Structure

```
cv-live/
├── main.py                    # FastAPI entrypoint (web server + dashboard)
├── upload_watcher.py          # Standalone S3 upload daemon
├── settings.yaml              # Runtime-tunable settings
├── .env                       # Static settings (you create this; optional)
├── requirements.txt           # Python dependencies
├── cv-live.service            # systemd unit for the camera/web app
├── cv-uploader.service        # systemd unit for the uploader
├── recordings/                # Where .mp4 files are saved (auto-created)
├── logs/                      # Application logs (auto-created)
├── static/                    # Dashboard CSS
├── templates/                 # Dashboard HTML
├── src/
│   ├── config.py              # Pydantic-validated config (static + runtime)
│   ├── service.py             # CameraService — orchestrates the pipeline
│   ├── recorder.py            # VideoRecorder — writes mp4 segments
│   ├── storage.py             # S3Uploader (with auto local-mode fallback)
│   ├── gesture.py             # Gesture enum, classifier, debouncer
│   ├── thermal.py             # CPU temperature reader (for thermal throttling)
│   ├── logging_setup.py       # Shared logging config for all processes
│   ├── models/
│   │   └── hand_landmarker.task   # MediaPipe AI model (downloaded by you)
│   └── processes/
│       ├── shared_state.py    # Cross-process shared memory
│       ├── capture.py         # Camera capture (separate process)
│       └── inference.py       # AI inference (separate process)
└── tests/                     # pytest unit tests
    ├── test_gesture_classifier.py
    ├── test_debouncer.py
    └── test_config.py
```

---

## Architecture & Performance

This section is for the curious / for anyone who wants to modify the internals.

CV Live uses a **multi-process pipeline** so that camera capture, AI inference, and video recording can all run on different CPU cores in parallel. This is what lets it sustain 30 FPS on a Raspberry Pi.

### The three processes

1. **CaptureProcess** (`src/processes/capture.py`)
   Owns the camera. Reads frames as fast as the camera can deliver them and writes them to a shared-memory buffer. Sets `CAP_PROP_BUFFERSIZE = 1` so we never serve stale frames after a brief stall.

2. **InferenceProcess** (`src/processes/inference.py`)
   Reads frames (zero-copy) from the shared buffer and runs MediaPipe hand detection on them. Throttles itself: drops to half-speed inference when CPU temperature exceeds 75°C. Sends gesture state-change events back to the main process via a queue.

3. **Main process** (`main.py` → `CameraService` in `src/service.py`)
   Hosts the FastAPI web server. Runs a thread that:
   - Waits on a per-consumer wakeup event (no polling, no busy loops)
   - Drains gesture events and feeds them to the `GestureDebouncer`
   - Draws overlays on the frame
   - Writes the frame to the `VideoRecorder` if recording is on
   - Encodes a JPEG (at 15 FPS, throttled) for the MJPEG stream

The three processes communicate via:
- **Shared memory** (`src/processes/shared_state.py`) — one zero-copy frame buffer with a deterministic name so leaked segments from a previous crash get cleaned up automatically.
- **Per-consumer events** — the producer wakes each consumer with its own `multiprocessing.Event`, so consumers never steal wakeups from each other.
- **A small result queue** for gesture state changes (depth 2; only state-change events are sent to avoid flooding).

### Why two services, not one?

The recorder and the uploader run as **independent systemd services**. The camera service writes finished `.mp4` files to disk and never touches AWS. The watcher service is the *only* code that ever uploads to S3. This separation means:

- A crash in the camera service can't lose pending uploads.
- A network outage doesn't affect recording.
- You can restart one without disturbing the other.

### Performance highlights

- ~30 FPS sustained on a Raspberry Pi 5 at 640×480
- Sub-millisecond consumer wakeup latency (event-driven, no polling)
- Frame drops impossible at the capture stage thanks to `CAP_PROP_BUFFERSIZE=1`
- MJPEG encoding throttled to 15 FPS so the dashboard stream doesn't compete with the recorder for CPU
- Strict-monotonic timestamps for MediaPipe so NTP/DST clock jumps can't break inference
- Disk space re-checked at every segment rollover, not just at the start
- Thermal throttling: detection rate doubles when the CPU exceeds 75°C

---

## Running the Tests

CV Live has a small `pytest` suite covering the pure logic (gesture classifier, debouncer, config). It does **not** require a camera or MediaPipe — `mediapipe` is imported lazily so the tests run fast and on any machine.

```bash
# Run all tests
python3 -m pytest tests/ -q

# Run a single test
python3 -m pytest tests/test_debouncer.py::test_holding_gesture_past_threshold_fires_once -q

# Run with verbose output
python3 -m pytest tests/ -v
```

You should see something like `24 passed in 0.05s`.

---

## Troubleshooting

### "Camera not found" / black video feed
- Check `CAMERA_INDEX` in your `.env`. Try `0`, then `1`, then `2`.
- On Linux, make sure your user is in the `video` group: `sudo usermod -aG video $USER` (then log out and back in).
- On Mac, the first time you run the app you may need to grant camera permissions in **System Settings → Privacy & Security → Camera**.

### "ModuleNotFoundError: No module named 'cv2'" (or any other module)
- You forgot to activate the virtual environment. Run `source .venv/bin/activate` and try again.
- Or you didn't install the dependencies — run `pip install -r requirements.txt`.

### "S3 disabled: ... Running in LOCAL MODE" but you wanted cloud mode
- The exact reason is in the log line. Common causes:
  - Bucket name typo
  - AWS credentials not set (run `aws configure` or set env vars)
  - The IAM user/role doesn't have `s3:ListBucket` or `s3:PutObject` on that bucket
  - Wrong `S3_REGION`

### Recording starts but the video is empty / 0 bytes
- The codec couldn't initialize. Check the logs for "Failed to initialize any video writer codec." Try installing FFmpeg system-wide (`brew install ffmpeg` or `sudo apt install ffmpeg`).

### The web dashboard works but the live feed is choppy / frozen
- Check disk usage — if the disk is nearly full, the recorder will pause. The dashboard's telemetry bar shows current disk %.
- Check CPU temperature on a Pi (`vcgencmd measure_temp`). If it's over 75°C, inference is being throttled.

### MediaPipe model file missing
```
FileNotFoundError: ... hand_landmarker.task
```
You skipped step 4 of installation. Run the `curl` command from the [installation section](#4-download-the-ai-model).

### "Address already in use" on port 8000
Another instance is already running. Kill it: `pkill -f "python3 main.py"` (or change the port in `main.py`).

---

## Tips, Dos & Don'ts

### ✅ DO

- **Do** run the app inside the virtual environment (`source .venv/bin/activate`).
- **Do** test that your camera works with a simple OpenCV script before assuming the app is broken.
- **Do** use a fast SD card or external SSD on the Raspberry Pi. Cheap/slow cards drop frames during recording.
- **Do** set `MODEL_COMPLEXITY=0` and `DETECTION_RATE=5` on the Raspberry Pi for best performance.
- **Do** start with **local mode** to verify everything works, then add S3 credentials later.
- **Do** check `logs/app.log` if anything weird happens — it captures errors that may not show up in the terminal.

### ❌ DON'T

- **Don't** set the resolution to 4K on the Raspberry Pi. 640×480 (default) or 720p are recommended for ML workloads.
- **Don't** delete the `.env` file mid-session if you've configured AWS in it — the app reads it once at startup.
- **Don't** run the app and the systemd service at the same time — they'll fight over the camera.
- **Don't** put your AWS keys in the README, in your git history, or anywhere public. Use `.env` (which is gitignored) or the AWS CLI's `aws configure` flow.
- **Don't** edit `settings.yaml` while the app is running unless you understand what you're doing — use the web dashboard instead, which validates inputs.

---

## Need More Detail?

- **[API.md](API.md)** — full REST API reference
- **[SERVICE.md](SERVICE.md)** — systemd deployment guide for Raspberry Pi
- **[CLAUDE.md](CLAUDE.md)** — architecture notes for developers
- **[src/TECHNICAL_DETAILS.md](src/TECHNICAL_DETAILS.md)** — internals of gesture detection and thermal throttling
- **`/docs`** (when the app is running) — interactive Swagger UI
