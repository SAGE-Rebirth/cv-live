# CV Live API Reference

**Version**: 1.0.0  
**Base URL**: `http://<device-ip>:8000`

## Monitoring

### Get Status
`GET /api/status`

Returns the current recording state of the system.

**Response**
`200 OK`
```json
{
  "recording": true
}
```

### Get Metrics
`GET /metrics`

Returns detailed system telemetry for observability.

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

Manually triggers the recording process. Equivalent to the "Two Fingers" gesture.

**Response**
`200 OK`
```json
{
  "status": "started"
}
```

### Stop Recording
`POST /api/stop`

Manually stops the recording process and finalizes the video file for upload. Equivalent to the "Five Fingers" gesture.

**Response**
`200 OK`
```json
{
  "status": "stopped"
}
```

---

## Configuration

### Get Configuration
`GET /api/config`

Returns all current configuration settings (Static from `.env` and Dynamic from `settings.yaml`).

**Response**
`200 OK`
```json
{
  "CAMERA_INDEX": 0,
  "DETECTION_RATE": 5,
  "MODEL_COMPLEXITY": 1,
  "RECORDING_SEGMENT_DURATION": 300,
  "MAX_DISK_USAGE_PERCENT": 85,
  "RETENTION_COUNT": 100,
  "S3_BUCKET_NAME": "my-bucket",
  "RECORDINGS_DIR": "recordings"
}
```

### Update Configuration
`POST /api/config`

Updates a dynamic setting and persists it to `settings.yaml`.

**Payload**
```json
{
  "key": "DETECTION_RATE",
  "value": 10
}
```

**Allowed Keys**: `DETECTION_RATE`, `MODEL_COMPLEXITY`, `RECORDING_SEGMENT_DURATION`, `MAX_DISK_USAGE_PERCENT`, `RETENTION_COUNT`.

**Response**
`200 OK`
```json
{
  "status": "updated",
  "key": "DETECTION_RATE",
  "value": 10
}
```

---

## Stream

### Video Feed
`GET /video_feed`

Returns a standard Motion JPEG (MJPEG) stream. 
**Usage**: Embed in an HTML `<img>` tag.

```html
<img src="http://localhost:8000/video_feed" />
```
