# Technical Deep Dive: Implementation Details

This document explains the internal mechanics of the Computer Vision system, specifically focusing on performance characteristics, frame flow, and the reasoning behind library choices.

## 1. Frame Capture (OpenCV & Multi-Processing)

### Mechanism
We do **not** read frames in the main loop. Instead, we use a dedicated **Capture Process** (`src/processes/capture.py`).
*   **Library**: `cv2.VideoCapture` (OpenCV).
*   **Architecture**: The capture process runs an infinite loop that grabs frames as fast as the hardware allows (Hardware FPS).
*   **Zero-Copy Transfer**: Frames are written directly into a pre-allocated `SharedMemory` block. This prevents the costly operation of pickling/copying large image arrays between Python processes.

### Performance
*   **Target FPS**: 30 FPS (Configurable).
*   **Latency**: < 5ms. Because the frame is always "hot" in shared memory, the inference and display processes always get the absolute latest image, eliminating "buffer lag."

---

### Mechanism
We use the **MediaPipe Tasks API** (`HandLandmarker`) for robust hand tracking. 
*   **Model**: Official Hand Landmarker Task Bundle (`src/models/hand_landmarker.task`).
*   **Running Mode**: `VIDEO`. Optimized for continuous frame processing.
*   **Output**: Normalized landmarks and hand handedness (Left/Right).

### Logic (`src/gesture.py`)
Geometric heuristics are applied to the 21 normalized 3D landmarks:
*   **Peace Sign (Start)**: Indices 8 (Index Tip) and 12 (Middle Tip) are significantly above their respective MCP knuckles, while others are curled.
*   **Open Palm (Stop)**: Identifies if at least 4 fingers are fully extended (Tip Y < MCP Y).

### Gesture Confirmation (Debouncing)
To prevent accidental triggers, a "Confirmation Window" is implemented:
1.  **Hold Required**: The user must hold the gesture for **2.0 seconds** (configurable).
2.  **Visual Feedback**: The system calculates `progress = elapsed / required_time` and displays a percentage overlay (e.g., "STOP_RECORDING: 45%").
3.  **Action**: The command executes only when progress reaches 100%. If the hand is dropped early, the timer resets.

### Performance & AI Throttling
*   **Inference Speed**: On a Pi 5, MediaPipe takes ~30-50ms per frame.
*   **Frame Skipping**: We do *not* run AI on every frame.
    *   **Detection Rate**: Configured to run every N frames (Default: 5).
    *   **Effective AI FPS**: ~6 FPS. This is sufficient for UI gestures but saves massive CPU power (80% reduction).
    *   **Thermal Throttling**: If CPU Temp > 75°C, the system dynamically drops the rate further (e.g., every 10 frames).

---

## 3. Video Recording (OpenCV VideoWriter)

### Mechanism
The system utilizes **OpenCV's `VideoWriter`** managed by `src/recorder.py`. 

### The Pipeline
1.  **Buffered Writing**: Frames are passed from the shared memory to the `VideoRecorder`.
2.  **Encoding**:
    *   **Container**: `.mp4`.
    *   **Codec Fallback**: The system attempts to initialize with `avc1` (H.264), falling back to `mp4v` or `MJPG` if hardware-specific encoders are unavailable.
3.  **Rotation & Cleanup**:
    *   **Auto-Segment**: Segments are rotated based on `RECORDING_SEGMENT_DURATION`.
    *   **Disk Watchdog**: Monitors disk percentage in real-time. If it hits the limit, it deletes the oldest file *before* starting a new write to prevent the OS from locking up.

### Why this is better
*   **Reliability**: Using OpenCV's native wrapper is more portable across different OS versions (macOS/Pi OS) compared to direct FFmpeg subprocess manipulation.
*   **Efficiency**: The recording logic is integrated into the main orchestrator while maintaining asynchronous behavior through process separation.

---

## 4. System Architecture (Multi-Processing)

To bypass Python's **Global Interpreter Lock (GIL)**, we split the heavier tasks:

| Component | Role | Resource Usage |
| :--- | :--- | :--- |
| **CaptureProcess** | Reads USB Camera | I/O Bound |
| **InferenceProcess** | Runs MediaPipe AI | CPU Bound (Core 1) |
| **Main Process** | Web Server / Recording | CPU Bound (Core 2) |
| **UploadWatcher** | S3 Uploads | Network / I/O |

This ensures that a heavy AI calculation never causes the Web Interface or Video Feed to stutter.

---

## 5. Logging & Observability
*   **Centralized Configuration**: Logging is configured in `main.py` to ensure all subprocesses and modules share the same handlers.
*   **Dual Output**: Logs are written to both `stdout` (for systemd/journalctl) and `logs/app.log` (for persistent debugging).
*   **Tracebacks**: Critical errors (like Inference failures) use `logger.exception` to capture full stack traces.
