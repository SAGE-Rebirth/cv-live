# Application Services Guide

This document explains how **Systemd Services** are used in the CV Live project to ensure reliability, auto-starting, and background execution.

## What is Systemd?
Systemd is the standard initialization system for Linux distributions (like Raspberry Pi OS). It manages "services"—programs that run in the background (daemons). 

Using systemd allows us to:
*   **Auto-Start**: Start the app automatically when the Pi boots.
*   **Resilience**: Automatically restart the app if it crashes.
*   **Logging**: Capture standard output (print statements) into system logs (`journalctl`).

## Project Services
This application uses **two** distinct services to decouple critical functionality:

### 1. Camera Service (`cv-live.service`)
*   **Status**: Primary Application.
*   **Function**: Runs `main.py`. Handles the Camera, AI Gesture Detection, and Recording.
*   **Behavior**: If this crashes, the video feed stops. Systemd will restart it immediately.

### 2. Upload Watcher (`cv-uploader.service`)
*   **Status**: Background Utility.
*   **Function**: Runs `upload_watcher.py`. Monitors the recording directory.
*   **Behavior**: Independent of the main app. If the main app halts, this service *continues* to run, ensuring any finished video files are safely uploaded to S3.

## Understanding the Service File
Here is a breakdown of the configuration file structure (e.g., `cv-live.service`):

```ini
[Unit]
Description=CV Live Camera Service
After=network.target video.target 
# ^ Waits for Network and Video drivers to be ready before starting.

[Service]
User=pi
# ^ The Linux user to run the script as.
WorkingDirectory=/home/pi/cv-live
# ^ Where the code lives.
ExecStart=/home/pi/cv-live/venv/bin/python main.py
# ^ The exact command to run. Note we use the Python inside the virtual environment (venv).
Restart=always
# ^ Implementation of "Crash Resilience".
RestartSec=5
# ^ Wait 5s before restarting to prevent rapid looping.
Environment=PYTHONUNBUFFERED=1
# ^ Ensures logs appear instantly in journalctl.

[Install]
WantedBy=multi-user.target
# ^ Tells systemd to start this when the system reaches "Multi-User" mode (standard boot).
```

## Management Commands

### Installation
To "install" a service, you copy it to the system folder and reload the daemon:
```bash
sudo cp *.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### Starting & Stopping
| Action | Command |
| :--- | :--- |
| **Start** | `sudo systemctl start cv-live` |
| **Stop** | `sudo systemctl stop cv-live` |
| **Restart** | `sudo systemctl restart cv-live` |

### Auto-Start on Boot
To make a service start when the Pi turns on:
```bash
sudo systemctl enable cv-live
```
To disable this:
```bash
sudo systemctl disable cv-live
```

### Checking Status
To see if it's running, crashed, or waiting:
```bash
sudo systemctl status cv-live
```

## Production Hardening (Cron)
To keep the system fresh, it is recommended to restart the service daily at 3 AM.

1.  Open crontab:
    ```bash
    crontab -e
    ```
2.  Add line:
    ```bash
    0 3 * * * sudo systemctl restart cv-live
    ```

## Viewing Logs
Python `print()` statements and errors are captured by the system journal.

**View Live Logs (Tail)**:
```bash
journalctl -u cv-live -f
```

**View All Logs**:
```bash
journalctl -u cv-live
```

## Troubleshooting
*   **Error 203/EXEC**: Usually means the path to `python` in `ExecStart` is wrong. Check if your `venv` path matches the file.
*   **ModuleNotFoundError**: The service isn't using the virtual environment. Ensure `ExecStart` points to `/venv/bin/python`, not `/usr/bin/python`.
*   **Permission Denied**: The `User` defined in the file doesn't have rights to write to the `recordings/` directory.
