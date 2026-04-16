# CV Live API Reference

**Version**: 1.1.0  
**Base URL**: `http://<device-ip>:8000`

## Monitoring

### Get Status
`GET /api/status`

Returns the current recording and gesture control state.

**Response**
`200 OK`
```json
{
  "recording": true,
  "gesture_enabled": false
}
```

### Get Metrics
`GET /metrics`

Returns detailed system telemetry for observability. `fps_configured` reflects the user's configured FPS from `settings.yaml`.

**Response**
`200 OK`
```json
{
  "recording": true,
  "disk_usage_percent": 45.2,
  "disk_free_gb": 12.5,
  "fps_configured": 30
}
```

---

## Control

### Start Recording
`POST /api/start`

Manually triggers the recording process. Equivalent to holding the **Peace Sign** gesture for the configured hold time.

**Response**
`200 OK`
```json
{
  "status": "started"
}
```

### Stop Recording
`POST /api/stop`

Manually stops the recording process and finalizes the current video segment. Equivalent to holding the **Open Palm** gesture.

**Response**
`200 OK`
```json
{
  "status": "stopped"
}
```

### Toggle Gesture Control
`POST /api/gesture-toggle`

Toggles gesture control on/off. When disabled (the default), only manual buttons, terminal commands, and API calls can start/stop recording. The inference process pauses (zero CPU) when gestures are off.

**Response**
`200 OK`
```json
{
  "status": "gestures enabled"
}
```

### Quit Application
`POST /api/quit`

Gracefully shuts down the entire application — stops recording, joins child processes, releases the camera and shared memory, then terminates the server. The response is sent before shutdown begins.

**Response**
`200 OK`
```json
{
  "status": "shutting down"
}
```

---

## Configuration

### Get Configuration
`GET /api/config`

Returns all current configuration settings (Static from `.env` and Runtime from `settings.yaml`).

**Response**
`200 OK`
```json
{
  "CAMERA_INDEX": 0,
  "FRAME_WIDTH": 640,
  "FRAME_HEIGHT": 480,
  "S3_BUCKET_NAME": "",
  "S3_REGION": "ap-south-1",
  "UPLOAD_MAX_RETRIES": 3,
  "LOG_LEVEL": "INFO",
  "RECORDINGS_DIR": "recordings",
  "LOGS_DIR": "logs",
  "DETECTION_RATE": 5,
  "MODEL_COMPLEXITY": 0,
  "RECORDING_SEGMENT_DURATION": 300,
  "MAX_DISK_USAGE_PERCENT": 85,
  "RETENTION_COUNT": 100,
  "FPS": 30,
  "GESTURE_CONFIRMATION_SECONDS": 3.0
}
```

### Update Configuration
`POST /api/config`

Updates a runtime setting and persists it to `settings.yaml`. Validation is performed by the pydantic model — invalid values return `400`.

**Payload**
```json
{
  "key": "DETECTION_RATE",
  "value": 10
}
```

**Editable Keys**: `DETECTION_RATE`, `MODEL_COMPLEXITY`, `RECORDING_SEGMENT_DURATION`, `MAX_DISK_USAGE_PERCENT`, `RETENTION_COUNT`, `FPS`, `GESTURE_CONFIRMATION_SECONDS`.

Changes to `FPS` reopen the camera at the new frame rate and roll the recorder to a fresh segment. Changes to `DETECTION_RATE` propagate to the inference process immediately via shared memory.

**Response**
`200 OK`
```json
{
  "status": "updated",
  "key": "DETECTION_RATE",
  "value": 10
}
```

**Error Response**
`400 Bad Request`
```json
{
  "error": "'FRAME_WIDTH' is not an editable runtime setting"
}
```

---

## Stream

### Video Feed
`GET /video_feed`

Returns a standard Motion JPEG (MJPEG) stream, throttled to the camera FPS (capped at 25 FPS).

**Usage**: Embed in an HTML `<img>` tag.

```html
<img src="http://localhost:8000/video_feed" />
```

---

## Quick Examples (curl)

```bash
# Check status
curl http://localhost:8000/api/status

# Start recording
curl -X POST http://localhost:8000/api/start

# Stop recording
curl -X POST http://localhost:8000/api/stop

# Change FPS live
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"key": "FPS", "value": 30}'

# Enable/disable gesture control
curl -X POST http://localhost:8000/api/gesture-toggle

# Shut down the app
curl -X POST http://localhost:8000/api/quit
```
