# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CV Live is a FastAPI-based gesture-controlled video recording system targeted at Raspberry Pi 5 (also runs on macOS). It uses MediaPipe hand detection to start/stop video recording via hand gestures, segments recordings, and uploads them to AWS S3 in the background.

## Common Commands

```bash
# Run the FastAPI server (production)
python3 main.py

# Run with hot reload (development)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run the upload watcher as a standalone process (normally a separate systemd service)
python3 upload_watcher.py

# Install dependencies
pip install -r requirements.txt

# One-time: download the MediaPipe Hand Landmarker model into src/models/
curl -L https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task \
  -o src/models/hand_landmarker.task

# Run tests (pytest)
python3 -m pytest tests/ -q

# Run a single test
python3 -m pytest tests/test_debouncer.py::test_holding_gesture_past_threshold_fires_once -q
```

There is no linter or build step configured in this repo. The test suite covers the pure logic (`GestureDebouncer`, landmark classifier, `Config` proxy) and does not require mediapipe or a camera — `mediapipe` is imported lazily inside `GestureDetector.__init__`.

The web dashboard is at `http://localhost:8000`, Swagger UI at `/docs`, MJPEG stream at `/video_feed`. See `API.md` for endpoint details.

## Architecture

This is a **multi-process** pipeline. Understanding the process boundaries is essential before changing anything in `src/processes/` or `src/service.py`.

### Process layout

Three execution contexts run concurrently and communicate via `multiprocessing` primitives:

1. **Main process** (`main.py` → `CameraService` in `src/service.py`)
   - Hosts the FastAPI app and the `_main_loop` thread.
   - Reads frames from shared memory, draws overlays, drains gesture results from `result_queue`, writes to `VideoRecorder`, and encodes JPEGs for the MJPEG stream.
2. **CaptureProcess** (`src/processes/capture.py`)
   - Owns the camera. Pushes raw frames into shared memory, increments `frame_index`.
3. **InferenceProcess** (`src/processes/inference.py`)
   - Runs MediaPipe gesture detection on shared-memory frames, sends gesture strings into `result_queue`. Throttles itself based on CPU temperature (`src/thermal.py`) — when temp > 75°C it doubles `DETECTION_RATE`.

### Shared state contract (`src/processes/shared_state.py`)

`SharedStateManager` exposes a single `multiprocessing.shared_memory` block (with a deterministic name `cv_live_frame` so leaked segments can be unlinked on restart), plus:
- `frame_index` (`multiprocessing.Value`): monotonic counter — primary source of truth for "is there a new frame?"
- `running_flag`, `recording_flag`: lifecycle/state flags.
- Per-consumer wakeup events created via `register_consumer()` — each consumer gets its own `multiprocessing.Event`, which the producer sets on every write. This avoids consumers stealing wakeups from each other. **Events must be registered in the parent process before child processes are spawned**, because spawn pickles the manager.

Consumers block on their own event with `wait(timeout=...)`, then `clear()` it, then check `frame_index` to confirm a real new frame. No polling, no busy loops.

Critical detail: child processes spawned with `spawn` semantics receive a pickled copy of the manager. They **must** call `self.shared_state.refresh()` at the start of `run()` to re-bind the numpy view onto the actual shared buffer — otherwise they read a stale local copy. Both `CaptureProcess` and `InferenceProcess` already do this; new child processes must do the same.

Two read APIs:
- `get_frame()` — copies out of shared memory. Use this when you need to mutate (overlays, recording).
- `peek_frame()` — zero-copy view onto the live buffer. Use this for read-only consumers (e.g. inference, where MediaPipe copies internally).

Writes are intentionally lock-free (tearing is acceptable for CV throughput).

### Gesture confirmation logic

Gesture debouncing lives in `GestureDebouncer` (`src/gesture.py`) — a plain class that the camera service feeds with raw `Gesture` enum values from the inference queue. The threshold is `Config.GESTURE_CONFIRMATION_SECONDS` (default 10s, configurable via env var), and it is the **single source of truth** used by both the action trigger and the dashboard progress overlay. The debouncer fires its `on_start`/`on_stop` callbacks exactly once per hold; releasing the gesture (or losing the hand) resets the state so the same gesture can re-fire.

The inference process emits state-change events only — including transitions to `None` ("hand lost") — so the debouncer is always in sync without flooding the queue.

### Recording → upload pipeline

Strict separation of concerns: **the camera service never touches S3**. It only writes mp4 files to disk. The upload watcher is the sole owner of uploads.

- `src/recorder.py` (`VideoRecorder`): segments the output every `RECORDING_SEGMENT_DURATION` seconds (counted in frames, not wall-clock) and enforces `MAX_DISK_USAGE_PERCENT` / `RETENTION_COUNT` (ring-buffer eviction of oldest files). Disk space is re-checked at every segment rollover.
- `src/storage.py` (`S3Uploader`): used **only** by the upload watcher. At init it verifies that (a) a bucket is configured, (b) boto3 can resolve credentials, and (c) `head_bucket` succeeds against the configured bucket. If any of these fail it logs the reason and runs in **LOCAL MODE** — uploads are skipped entirely, but `_cleanup_local_storage()` still enforces `RETENTION_COUNT` so the disk doesn't fill up. This means a user can run the system with no S3 setup at all and recordings just accumulate locally (rolling deletion of the oldest).
- `upload_watcher.py` runs as a **separate systemd service** (`cv-uploader.service`). It scans the recordings directory for finished `.mp4` files, uploads them, and deletes the local copy on success. After 3 failures it moves files to a `quarantine/` directory **outside** the recordings folder (so non-recursive globbing never picks them back up). Success is detected by checking whether the source file still exists after `_upload_worker` returns — don't change that contract without updating both sides.

### Configuration system (`src/config.py`)

Two pydantic models behind a single `Config` proxy:

- **`_StaticSettings`** (pydantic-settings `BaseSettings`): camera, S3, paths, log level, gesture timeout. Loaded from env vars / `.env` at process start, validated by pydantic. Restart required to change.
- **`_RuntimeSettings`** (pydantic `BaseModel`): `DETECTION_RATE`, `MODEL_COMPLEXITY`, `RECORDING_SEGMENT_DURATION`, `MAX_DISK_USAGE_PERCENT`, `RETENTION_COUNT`. Loaded from `settings.yaml`, mutated via `Config.update_setting(...)` (called by `POST /api/config`), persisted back to YAML. Pydantic validates new values against the field constraints (`ge`, `le`, etc.).

Access is always `Config.KEY` regardless of tier — the proxy's `__getattr__` checks both models. **To add a new runtime-tunable setting**: add a field to `_RuntimeSettings` with a sensible default and validation; the API whitelist (`Config.editable_keys`) is derived from the model so no other change is needed.

**Cross-process caveat**: each process owns its own `Config` instance, so a runtime mutation in the API process is not visible to the capture/inference children until they re-read the YAML. Currently they don't — this is a known limitation inherited from the previous metaclass version. If this becomes a real problem, switch the runtime store to a `multiprocessing.Manager` dict or watch the YAML file.

### Deployment

Two systemd units ship with the repo: `cv-live.service` (camera/API) and `cv-uploader.service` (watcher). They are independent — the watcher exists specifically so uploads survive crashes/restarts of the main service. See `SERVICE.md` for install steps.

### Logging

Child processes spawned with the `spawn` start method do **not** inherit the parent's logging config. `src/logging_setup.py` exposes a `setup_logging(component)` helper that **every** entry point — `main.py`, `upload_watcher.py`, and each `Process.run()` method — calls at startup. Any new child process must do the same or its logs will silently disappear.

## Notes for editing

- The README references `src/main.py` in its architecture section, but the actual entrypoint is `main.py` at the repo root.
- `requirements.txt` does not pin versions and there is no lockfile.
- `src/ffmpeg_recorder.py` and `src/camera.py` (`ThreadedCamera`) both exist but are dead code; the active path is `CaptureProcess` + `VideoRecorder`.
- The README's mention of FFmpeg/H.264 CRF compression is stale — the current recorder uses OpenCV `VideoWriter` with codec fallback (avc1 → mp4v → MJPG).
- Detailed internals (thermal throttling thresholds, gesture detection tuning) are documented in `src/TECHNICAL_DETAILS.md`.
