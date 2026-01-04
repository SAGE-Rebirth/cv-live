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

## 2. Gesture Recognition (MediaPipe)

### Mechanism
We use **Google MediaPipe Hands**, a graph-based framework for hand tracking.
*   **Model**: Single-hand detection model (`max_num_hands=1`).
*   **Input**: RGB Images (converted from OpenCV's BGR).
*   **Output**: 21 3D Landmarks per hand.

### Logic (`src/gesture.py`)
Instead of complex Machine Learning classifiers, we use efficient **Geometric Heuristics**:
*   **Peace Sign (Start)**: Checks if Index and Middle finger tips are **higher** (lower Y-coordinate) than their knuckles, while Ring and Pinky are **lower**.
*   **Open Palm (Stop)**: Checks if at least 4 fingers are fully extended.

### Performance & AI Throttling
*   **Inference Speed**: On a Pi 5, MediaPipe takes ~30-50ms per frame.
*   **Frame Skipping**: We do *not* run AI on every frame.
    *   **Detection Rate**: Configured to run every N frames (Default: 5).
    *   **Effective AI FPS**: ~6 FPS. This is sufficient for UI gestures but saves massive CPU power (80% reduction).
    *   **Thermal Throttling**: If CPU Temp > 75°C, the system dynamically drops the rate further (e.g., every 10 frames).

---

## 3. Video Recording (FFmpeg Pipeline)

### Mechanism
We bypass OpenCV's built-in `VideoWriter` in favor of a direct **FFmpeg Subprocess** (`src/ffmpeg_recorder.py`). This allows us to access professional-grade compression features not easily available in OpenCV.

### The Pipeline
1.  **Input**: Raw Video Frames (BGR/YUV) are written to `subprocess.stdin.write()`.
2.  **Encoding**:
    *   **Codec**: `libx264` (H.264).
    *   **Preset**: `ultrafast` (Minimizes CPU usage, slightly larger file size).
    *   **CRF (Constant Rate Factor)**: `23` (Maintains visual quality while optimizing size, unlike fixed bitrate).
3.  **Container**: Output is muxed into `.mp4`.

### Why this is better
*   **Space**: H.264 with CRF is ~90% smaller than MJPEG or raw AVI.
*   **Speed**: Operating on a separate thread ensures disk writes never block the camera or AI.

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
