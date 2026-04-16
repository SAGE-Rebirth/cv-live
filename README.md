# CV Live — Gesture-Controlled Camera Recorder

**CV Live** is a smart camera recorder that watches your hand gestures and starts/stops video recording on its own. It's designed to run continuously on a Raspberry Pi 5 (or any Mac/PC with a webcam) and can optionally upload finished recordings to AWS S3 — but it works perfectly fine without any cloud setup at all.

You can control it from a **web dashboard** in your browser, from the **terminal** (headless mode for Pi), or purely through **hand gestures**.

> **Recently improved**
> - **Gesture toggle** — gestures are **off by default** to prevent accidental recordings. Enable them from the dashboard switch, terminal (`g` key), or API. When off, the inference process sleeps (zero CPU from MediaPipe).
> - **Gesture stability fix** — added hysteresis margin to finger detection so gestures don't flicker during transitions (peace ↔ palm).
> - **CLI with headless mode** — run `python3 main.py --headless` for terminal-only control on a Pi with no GUI. Press `r`/`s`/`g`/`q` to start, stop, toggle gestures, or quit.
> - **Quit button** in the dashboard header (power icon) — cleanly shuts down the server, camera, and all child processes.
> - **H.264 (avc1) codec** — recordings now use H.264 instead of MPEG-4 Part 2, so they open in VS Code, QuickTime, VLC, and browsers.
> - **Actual FPS tracking** — the recorder uses the real FPS reported by the camera driver, not the requested value. No more 2x-speed videos when the driver ignores your FPS request.
> - **Child process auto-recovery** — if the capture or inference process crashes, the main loop detects it within 5 seconds and respawns it automatically.
> - **Live FPS dropdown** in the dashboard (15 / 24 / 30 / 60) — changes apply instantly without restarting.
> - **Faster gesture response** — default hold time is now **3 seconds** (was 10s), and it's tunable from the Settings panel.
> - **BGR-to-RGB fix** — gesture detection is now reliable (MediaPipe was receiving BGR data labeled as RGB, causing intermittent hand tracking failures).

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
9. [Tuning Performance & Responsiveness](#tuning-performance--responsiveness)
10. [Local Mode vs Cloud Mode](#local-mode-vs-cloud-mode)
11. [API Reference](#api-reference)
12. [Running on a Raspberry Pi (Auto-Start)](#running-on-a-raspberry-pi-auto-start)
13. [Project Structure](#project-structure)
14. [Architecture & Performance](#architecture--performance)
15. [Running the Tests](#running-the-tests)
16. [Troubleshooting](#troubleshooting)
17. [Tips, Dos & Don'ts](#tips-dos--donts)

---

## What It Does

- **Watches your camera** continuously using a hand-tracking AI model (Google MediaPipe).
- **Detects two hand gestures**:
  - ✌️ **Peace sign** (index + middle finger up) → starts recording
  - 🖐️ **Open palm** (all five fingers up) → stops recording
- **Records video** to your local disk as `.mp4` files (H.264 codec), automatically split into 5-minute chunks.
- **Uploads each chunk to AWS S3** in the background, *if* you give it AWS credentials. If you don't, it just keeps the files locally.
- **Manages disk space** automatically — when the disk gets full, it deletes the oldest recording first so it can keep going forever without manual intervention.
- **Provides a web dashboard** so you can watch the live feed and tweak settings from any phone or computer on the network.
- **Works headless** — run with `--headless` for terminal-only control on a Raspberry Pi with no display.
- **Survives crashes** — the recorder and the uploader run as two separate background services, and crashed child processes are automatically respawned.

---

## How It Works (Big Picture)

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Camera      │───▶│  Hand AI     │───▶│  Debouncer   │
│  (capture)   │    │  (inference) │    │  (3s hold)   │
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
- ❌ A separate FFmpeg install — `opencv-contrib-python` (in `requirements.txt`) ships with the codecs the recorder needs
- ❌ A GPU — MediaPipe runs on the CPU

> **macOS users**: if you previously installed `opencv-python` (without `-contrib`), recordings may save as 0-byte files because the standard wheel ships without FFmpeg. Run `pip uninstall opencv-python && pip install opencv-contrib-python` to fix it. The `requirements.txt` in this repo already specifies the contrib build.

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
| **Runtime** | `settings.yaml` | Live, via the web dashboard | FPS, detection rate, segment length, disk limit, gesture hold time |

You don't *need* to create either file — both have safe defaults baked in.

### The `.env` file (static settings)

Create a file named `.env` in the project folder. Here's a complete annotated example — copy it and only uncomment what you actually want to change:

```ini
# ========== Camera ==========
# Which camera to use. 0 is usually the default webcam. Try 1 if 0 fails.
CAMERA_INDEX=0
FRAME_WIDTH=640
FRAME_HEIGHT=480

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

# Camera frame rate. Live-tunable from the dashboard's FPS dropdown — when
# you change it, the capture process reopens the camera and the recorder
# rolls over to a fresh segment automatically. Note: the recorder uses the
# ACTUAL FPS the camera driver reports, not the requested value, so
# playback speed is always correct.
FPS: 30

# How long (in seconds) you must hold a gesture before it triggers an action.
# Lower = snappier response. 3s is the sweet spot for most users.
GESTURE_CONFIRMATION_SECONDS: 3.0
```

All values are validated when you save them — bad inputs (like a negative `DETECTION_RATE`) are rejected.

---

## Running the App

Make sure your virtual environment is active (`source .venv/bin/activate`), then:

### Standard mode (web dashboard + terminal controls)

```bash
python3 main.py
```

You'll see:

```text
Dashboard: http://localhost:8000
API docs:  http://localhost:8000/docs

--- CV Live Terminal Controls ---
  r = start recording
  s = stop recording
  g = toggle gesture control
  q = quit
--------------------------------
```

### Headless mode (no browser needed — for Raspberry Pi)

```bash
python3 main.py --headless
```

Control everything from the terminal with single keypresses (`r`, `s`, `q`). The API is still available for remote control via `curl`.

### Custom host / port

```bash
python3 main.py --port 9000
python3 main.py --host 127.0.0.1 --port 80
python3 main.py --headless --port 9000
```

### Development mode (auto-reload on file changes)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Stopping the app

Terminal controls:

| Key | Action |
|---|---|
| `r` | Start recording |
| `s` | Stop recording |
| `g` | Toggle gesture control on/off |
| `q` | Quit (clean shutdown) |

You can also quit from the dashboard (power icon, top-right) or with **Ctrl+C**. All methods trigger a clean shutdown: recording is stopped, child processes are joined, shared memory is released, and the camera is freed.

---

## Using the Web Dashboard

Open a browser and go to:

- **From the same machine**: `http://localhost:8000`
- **From another device on the same network**: `http://<your-device-ip>:8000`

You'll see:

- A **live video feed** showing what the camera sees, with gesture overlays drawn on top.
- A **status badge** (IDLE / RECORDING) — turns red and pulses while recording.
- **Stats cards**:
  - **FPS dropdown** — pick `15`, `24`, `30`, or `60`. The camera reopens immediately. The recorder uses the **actual** FPS the driver reports, so playback speed is always correct even if the driver ignores your request.
  - **Resolution** — current capture resolution.
  - **Disk** — current disk usage percentage with a colored bar.
  - **Gesture Control** — toggle switch to enable/disable gesture detection (off by default), plus a quick reminder of the two gestures. When off, the inference process sleeps and uses zero CPU.
- **Manual control buttons**: Start Recording / Stop Recording (always work, regardless of gesture toggle).
- **Settings button** (gear icon) — opens a modal with runtime-tunable settings.
- **Quit button** (power icon) — shuts down the entire application with a confirmation dialog.

All dashboard changes are validated by the backend and persisted to `settings.yaml` so they survive restarts.

### Finding your device's IP address

- **Mac**: `ipconfig getifaddr en0`
- **Linux/Pi**: `hostname -I`
- **Windows**: `ipconfig`

---

## Gestures

**Gesture control is disabled by default** to prevent accidental recordings. Enable it from the dashboard toggle switch, the terminal (`g` key), or the API (`POST /api/gesture-toggle`).

When enabled and the camera sees your hand, it'll show a small overlay on the video feed with the gesture name and a progress bar.

| Gesture | Action |
|---|---|
| ✌️ **Peace sign** (index + middle finger up, others down) | Start recording |
| 🖐️ **Open palm** (all five fingers up) | Stop recording |

You must **hold the gesture steady** for the configured number of seconds (default **3 seconds** — you can change this from the dashboard's settings panel). This prevents accidental triggers from random hand movements.

The dashboard overlay will count up `0% → 100%` so you know how long is left. When it hits **CONFIRMED**, the action fires.

After it fires, you have to lower your hand (or change the gesture) before the same one can fire again — the system doesn't spam-toggle while you keep holding.

---

## Tuning Performance & Responsiveness

Everything in this section can be changed **live from the dashboard** — no restart, no editing files.

### "I want it to feel snappier"

| Setting | Default | Try |
|---|---|---|
| **Gesture Hold Time** | `3.0s` | `1.5s` (very fast) — accidental triggers become more likely |
| **AI Detection Rate** | `5` (every 5th frame) | `2` or `3` — more CPU but the AI sees the gesture sooner |
| **FPS** | `30` | `60` — only useful if your camera actually supports it |

### "I want it to use less CPU / not overheat the Pi"

| Setting | Default | Try |
|---|---|---|
| **AI Detection Rate** | `5` | `8`–`10` |
| **FPS** | `30` | `15` or `24` — recording is still smooth, AI runs less |
| **Model Complexity** | `0` (already light) | leave at `0` |

The Pi-specific thermal protection (auto-throttling above 75°C) kicks in automatically — you don't need to configure anything for it.

### "I want longer / shorter video chunks"

Change **Segment Duration (Seconds)** in the Settings modal. Default is 300 (5 minutes). Each chunk is uploaded independently to S3 (in cloud mode) so smaller chunks = faster cloud delivery but more files; larger chunks = fewer files but more data lost if something interrupts an in-progress segment.

### "I'm running out of disk space"

Two settings work together:

- **Max Disk Usage (%)** — when the disk is more than this percent full, the **oldest** recording is deleted to make room.
- **Retention Count** — never keep more than this many `.mp4` files locally regardless of disk usage.

Both checks run automatically; you can never get into a "disk full, app stuck" state.

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
| `GET` | `/metrics` | Disk usage, free space, actual FPS |
| `POST` | `/api/start` | Start recording manually |
| `POST` | `/api/stop` | Stop recording manually |
| `POST` | `/api/quit` | Gracefully shut down the app |
| `POST` | `/api/gesture-toggle` | Toggle gesture control on/off |
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

# Toggle gesture control on/off
curl -X POST http://localhost:8000/api/gesture-toggle

# Shut down the app remotely
curl -X POST http://localhost:8000/api/quit
```

For full request/response details, see [API.md](API.md) or the Swagger UI.

---

## Running on a Raspberry Pi (Auto-Start)

For production use on a Pi, you'll want the app to start automatically on boot and restart itself if it crashes. CV Live ships with two `systemd` service files for this:

- `cv-live.service` — runs the camera/web app (`main.py --headless`)
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
├── main.py                    # FastAPI entrypoint + CLI (--headless, --port)
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
│   ├── recorder.py            # VideoRecorder — writes H.264 mp4 segments
│   ├── storage.py             # S3Uploader (with auto local-mode fallback)
│   ├── gesture.py             # Gesture enum, classifier, debouncer
│   ├── thermal.py             # CPU temperature reader (for thermal throttling)
│   ├── logging_setup.py       # Shared logging config for all processes
│   ├── models/
│   │   └── hand_landmarker.task   # MediaPipe AI model (downloaded by you)
│   └── processes/
│       ├── shared_state.py    # Cross-process shared memory + actual_fps
│       ├── capture.py         # Camera capture (separate process, timeout-guarded)
│       └── inference.py       # AI inference (separate process)
└── tests/                     # pytest unit tests (no camera/MediaPipe needed)
    ├── test_gesture_classifier.py  # Landmark → Gesture classification
    ├── test_debouncer.py           # Gesture hold/confirm state machine
    └── test_config.py              # Config proxy, validation, persistence
```

---

## Architecture & Performance

This section is for the curious / for anyone who wants to modify the internals.

CV Live uses a **multi-process pipeline** so that camera capture, AI inference, and video recording can all run on different CPU cores in parallel. This is what lets it sustain 30 FPS on a Raspberry Pi.

### The three processes

1. **CaptureProcess** (`src/processes/capture.py`)
   Owns the camera. Reads frames with a 5-second timeout (so a camera disconnect doesn't hang the process forever) and writes them to a shared-memory buffer. Sets `CAP_PROP_BUFFERSIZE = 1` so we never serve stale frames. Publishes the **actual** FPS the driver reported to shared state so the recorder uses the correct value for the MP4 header.

2. **InferenceProcess** (`src/processes/inference.py`)
   Reads frames (copy from shared buffer) and runs MediaPipe hand detection on them, with proper BGR→RGB conversion. Throttles itself: drops to half-speed inference when CPU temperature exceeds 75°C. Reads `DETECTION_RATE` from shared memory so dashboard changes apply immediately. Sends gesture state-change events back to the main process via a queue.

3. **Main process** (`main.py` → `CameraService` in `src/service.py`)
   Hosts the FastAPI web server. Runs a thread that:
   - Waits on a per-consumer wakeup event (no polling, no busy loops)
   - Checks child process health every 5 seconds and respawns crashed children
   - Syncs the recorder's FPS with the actual camera FPS
   - Drains gesture events and feeds them to the `GestureDebouncer`
   - Draws overlays on the frame
   - Writes the frame to the `VideoRecorder` if recording is on
   - Encodes a JPEG (throttled to 25 FPS max) for the MJPEG stream

**Important**: `CameraService` is constructed lazily inside the FastAPI lifespan handler, not at module level. This prevents child processes (which re-import `__main__` under `spawn` semantics on macOS) from destroying the parent's shared memory.

### Cross-process communication

- **Shared memory** (`src/processes/shared_state.py`) — one frame buffer with a deterministic name (`cv_live_frame`) so leaked segments from a previous crash get cleaned up automatically.
- **Per-consumer events** — the producer wakes each consumer with its own `multiprocessing.Event`, so consumers never steal wakeups from each other.
- **A small result queue** for gesture state changes (depth 2; only state-change events are sent to avoid flooding).
- **Shared `multiprocessing.Value`s** — `target_fps`, `actual_fps`, and `target_detection_rate` allow the API process and child processes to communicate live configuration changes without re-reading YAML.

### Why two services, not one?

The recorder and the uploader run as **independent systemd services**. The camera service writes finished `.mp4` files to disk and never touches AWS. The watcher service is the *only* code that ever uploads to S3. This separation means:

- A crash in the camera service can't lose pending uploads.
- A network outage doesn't affect recording.
- You can restart one without disturbing the other.

### Performance highlights

- ~30 FPS sustained on a Raspberry Pi 5 at 640×480 (and 60 FPS on a Mac with the dropdown)
- Sub-millisecond consumer wakeup latency (event-driven, no polling)
- Frame drops impossible at the capture stage thanks to `CAP_PROP_BUFFERSIZE=1`
- MJPEG encode rate auto-follows the camera FPS, capped at 25 FPS
- Strict-monotonic timestamps for MediaPipe so NTP/DST clock jumps can't break inference
- Disk space re-checked at every segment rollover, not just at the start
- Thermal throttling: detection rate doubles when the CPU exceeds 75°C
- Codec probed at startup with actual frame writes — fails fast if no working codec
- Wall-clock segment rollover — robust regardless of FPS changes mid-recording
- Camera read timeout (5 seconds) prevents indefinite hangs on disconnect

---

## Running the Tests

CV Live has a `pytest` suite covering the pure logic (gesture classifier, debouncer, config). It does **not** require a camera or MediaPipe — `mediapipe` is imported lazily so the tests run fast and on any machine.

```bash
# Run all tests
python3 -m pytest tests/ -q

# Run a single test
python3 -m pytest tests/test_debouncer.py::test_holding_gesture_past_threshold_fires_once -q

# Run with verbose output
python3 -m pytest tests/ -v
```

You should see something like `25 passed in 0.05s`.

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

### "No working video codec found!"
The codec probe runs at startup and tests that frames can actually be written (not just that the writer opens). If it fails:

```bash
pip uninstall opencv-python
pip install opencv-contrib-python
```

`opencv-contrib-python` ships with FFmpeg-enabled wheels on macOS and Linux, so the `avc1` (H.264) and `mp4v` codecs both work out of the box.

### Recordings aren't appearing in the `recordings/` folder
Look at the terminal log when you start a recording. The recorder prints exactly where it's writing:

```
Recording -> /path/to/recordings/rec_20260416_182546.mp4 (codec=avc1, 640x480 @ 30fps)
```

And when you stop:

```
Segment closed: /.../rec_20260416_182546.mp4 (193 frames, 1.2 MB)   ← success
```

If the file size is 0 bytes, the codec probe should have caught it at startup. If it didn't, try switching codecs by reinstalling opencv-contrib-python.

### Recording works but the file is corrupted / unplayable
You're probably stopping the app via SIGKILL or unplugging the Pi mid-recording. The file gets finalized only when `_close_file` runs. Use Ctrl+C, the dashboard quit button, the `q` terminal key, or `systemctl stop cv-live` for a graceful shutdown.

### The web dashboard works but the live feed is choppy / frozen
- Check disk usage — if the disk is nearly full, the recorder will pause.
- Check CPU temperature on a Pi (`vcgencmd measure_temp`). If it's over 75°C, inference is being throttled.

### MediaPipe model file missing
```
FileNotFoundError: ... hand_landmarker.task
```
You skipped step 4 of installation. Run the `curl` command from the [installation section](#4-download-the-ai-model).

### "Address already in use" on port 8000
Another instance is already running. Kill it: `pkill -f "python3 main.py"` or use `--port 9000`.

### Gestures detected but never fire
Check `logs/app.log` for `[INFER]` lines like `Gesture change: None -> START_RECORDING`. If these appear but `Gesture confirmed` never does, the debouncer isn't getting continuous ticks — this was a past bug that's been fixed. If detection doesn't appear at all, ensure the model file exists at `src/models/hand_landmarker.task`.

---

## Tips, Dos & Don'ts

### ✅ DO

- **Do** run the app inside the virtual environment (`source .venv/bin/activate`).
- **Do** test that your camera works with a simple OpenCV script before assuming the app is broken.
- **Do** use a fast SD card or external SSD on the Raspberry Pi. Cheap/slow cards drop frames during recording.
- **Do** set `MODEL_COMPLEXITY=0` and `DETECTION_RATE=5` on the Raspberry Pi for best performance.
- **Do** start with **local mode** to verify everything works, then add S3 credentials later.
- **Do** check `logs/app.log` if anything weird happens — it captures errors that may not show up in the terminal.
- **Do** use `--headless` on a Pi with no display attached.

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
