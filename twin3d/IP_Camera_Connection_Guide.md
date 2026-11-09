# BE_Project_main/twin3d - IP Camera Connection Guide

## Overview
This guide explains how to connect mobile IP cameras to the Twin3D digital twin surveillance system for person detection and tracking. The system uses YOLO + ByteTrack for object detection and Redis + PostgreSQL for data processing.

## Prerequisites
- Docker Desktop running (confirmed working)
- BE_Project_main/twin3d project set up
- .env file configured (already created)
- Mobile IP camera with RTSP capability
- Computer and phone on same local network

## Project Components Involved

| Component | Role |
|-----------|------|
| **CV Service** | Receives RTSP stream, runs YOLO detection, ByteTrack tracking |
| **Backend API** | Processes floor coordinates, generates alerts, WebSocket to frontend |
| **Frontend** | 3D digital twin display, alert panel |
| **PostgreSQL** | Stores history snapshots (10Hz) |
| **Redis** | Real-time data buffering, zone occupancy |

## RTSP URL Format

The system expects an RTSP URL in the `.env` file under `CAM01_URL`:

```env
CAM01_URL=rtsp://<phone-ip>:<port>/<stream_path>
```

### Common Mobile Camera App RTSP URLs:

#### 📱 IP Webcam (Android)
- **Default RTSP**: `rtsp://192.168.1.XX:8080/h264_stream`
- **MJPEG stream**: `rtsp://192.168.1.XX:8080/h264_mjpeg`
- **Settings**: Open IP Webcam → Start Server → Menu → RTSP URL

#### 📱 DroidCam (Android/iOS)
- **RTSP URL**: `rtsp://192.168.1.XX:8081/video`
- **Requires**: DroidCam XS server running on computer
- **Settings**: App → Settings → RTSP mode

#### 📱 AtHome Camera (Android/iOS)
- **RTSP URL**: `rtsp://192.168.1.XX:554/stream`
- **Settings**: AtHome → Monitor → RTSP

#### 📱 ManyCam
- **RTSP URL**: `rtsp://192.168.1.XX:554/live`
- **Settings**: ManyCam → Source → RTSP

## Step-by-Step: Finding Your RTSP URL

### For IP Webcam (Most Common):

1. **Install app** on your phone:
   - Google Play Store → "IP Webcam" by IP Camera Dev

2. **Connect to same WiFi**:
   - Ensure phone and computer are on same network

3. **Start the stream**:
   - Open IP Webcam app
   - Tap **Start Server** button
   - Grant permission for camera/microphone

4. **Find the RTSP URL**:
   - Look at the text below "Stop Server" button
   - Or tap **Menu** (three dots) → **RTSP URL**
   - Example: `rtsp://192.168.1.50:8080/h264_stream`

5. **Test with VLC (optional)**:
   - Open VLC media player on computer
   - Media → Open Network Stream
   - Paste RTSP URL
   - Play → Verify video appears

### For Other Apps:

| App | Finding Steps |
|-----|---------------|
| **DroidCam** | Open app → Settings → RTSP URL shown directly |
| **AtHome Camera** | Monitor view → Settings (gear icon) → RTSP |
| **ManyCam** | Main screen → Source → RTSP tab |
| **Other IP Camera Apps** | Look for "Share", "RTSP", "Stream" in settings |

## Configuration Steps

### Step 1: Update .env File

Edit `C:\Users\abhij\OneDrive\source\BE_Project_main\twin3d\.env`:

```powershell
# From project directory
notepad .env
```

**Modify line 7:**
```env
CAM01_URL=rtsp://192.168.1.50:8080/h264_stream
# Replace IP and path with your camera's URL
```

**Full .env example:**
```env
POSTGRES_USER=twin
POSTGRES_PASSWORD=Pass@123
POSTGRES_DB=twin
CAMERAS=cam01,cam02,cam03,cam04
FLOOR_ID=F1
# CV worker (real cameras): rtsp://user:pass@192.168.1.20:554/stream1
CAM01_URL=rtsp://192.168.1.50:8080/h264_stream
```

### Step 2: Start CV Service

```powershell
# From project directory
cd C:\Users\abhij\OneDrive\source\BE_Project_main\twin3d

# Start only CV profile (postgres+redis already running from demo)
docker compose --profile cv up -d --build
```

### Step 3: Verify Connection

```powershell
# Check container status
docker compose ps

# Should show: cv service running

# View CV logs (watch for RTSP connection messages)
docker compose logs cv -f
```

**Expected log messages:**
```
cv_1  | INFO: Connecting to RTSP stream: rtsp://192.168.1.50:8080/h264_stream
cv_1  | INFO: OpenCV FFmpeg capturing started
cv_1  | INFO: YOLO detection initialized
cv_1  | INFO: ByteTrack tracker started
```

### Step 4: Access Person Detection

```powershell
# Open frontend
http://localhost:5173

# Expected:
# - Detected people shown as boxes
# - Person IDs tracked with ByteTrack
# - Floor coordinates in meters
# - Alerts when people enter "red zones"
```

### Step 5: Calibration (First Time Only)

Before accurate floor positioning:

```powershell
# 1. Grab one frame from camera
# 2. Measure 4+ floor points in meters (room corners)
# 3. Run calibration

python -m cv_service.calibrate --image frame.jpg --world "2,2;10,2;10,8;2,8" --out calib/cam01.json
```

**Floor point measurement example:**
- Point 1: Bottom-left corner = (2, 2) meters
- Point 2: Bottom-right corner = (10, 2) meters  
- Point 3: Top-right corner = (10, 8) meters
- Point 4: Top-left corner = (2, 8) meters

## Profile Configuration

### Demo Profile (No Real Camera)
```powershell
# Starts fake data producer (200 simulated people)
docker compose --profile demo up -d --build
```
- Good for testing UI without camera
- People walk into red zones automatically
- API: http://localhost:8000/docs

### CV Profile (With Real Camera)
```powershell
# Starts CV worker with your RTSP stream
docker compose --profile cv up -d --build
```
- Requires CAM01_URL in .env
- Real person detection and tracking
- Full surveillance pipeline

### Combined (Demo + CV)
```powershell
# Start both profiles
docker compose --profile demo --profile cv up -d --build
```
- Fake people + real camera processing
- Useful for development/testing

## Troubleshooting

### Common Issues & Solutions

| Problem | Solution |
|---------|----------|
| **CV container restarts** | Check logs: `docker compose logs cv`; verify RTSP URL format; ensure phone/computer on same WiFi |
| **No people detected** | - Check camera angle/lighting<br>- Re-calibrate floor coordinates<br>- Verify `OPENCV_FFMPEG_CAPTURE_OPTIONS` setting |
| **RTSP connection timeout** | - Verify RTSP URL correct<br>- Check phone firewall<br>- Try different RTSP port (8080 vs 554 vs 8081)<br>- Restart CV: `docker compose restart cv` |
| **Person count incorrect** | Re-calibrate with more accurate floor measurements<br>Ensure camera is perpendicular to floor |
| **Coordinates wrong** | Calibration file `calib/cam01.json` may need updating<br>Measure floor points more precisely |
| **Frontend shows no detection** | Check API docs: http://localhost:8000/docs<br>Verify backend receiving stream |

### Logs Analysis

```powershell
# Real-time log viewing
docker compose logs cv -f

# Check last 50 lines
docker compose logs cv --tail=50

# Specific error patterns
# "Cannot open stream" → RTSP URL wrong or unreachable
# "YOLO model not found" → Rebuild: docker compose up -d --build
# "Redis connection lost" → Check: docker compose ps
```

### Port Conflicts

| Port | Used By | Default |
|------|---------|---------|
| 5432 | PostgreSQL | Yes (in compose.yml) |
| 6379 | Redis | Yes (in compose.yml) |
| 5173 | Frontend | Yes (in compose.yml) |
| 8000 | Backend API | Yes (in compose.yml) |
| 8080 | IP Webcam | Mobile app (may conflict) |
| 554 | Standard RTSP | Mobile app / camera |
| 8081 | DroidCam | Mobile app |

**If port 8080 conflict:** Change IP Webcam port in app settings, or update compose.yml ports section.

## Camera Best Practices

### ✅ Do's:
- **Same network**: Phone and computer must be on same WiFi (not cellular + WiFi)
- **Good lighting**: Ensure room has adequate lighting for YOLO detection
- **Stable camera**: Mount phone securely, avoid shaking
- **Perpendicular angle**: Camera should be angled straight down at floor, not tilted
- **Clear floor**: Keep floor area visible, avoid obstacles
- **Test RTSP first**: Verify URL works in VLC before integrating

### ❌ Don'ts:
- **Different networks**: Phone on cellular, computer on WiFi (won't work)
- **Low light**: YOLO needs adequate illumination
- **Moving camera**: Fixed position required for tracking
- **Obstructed view**: Ensure people fully visible in frame
- **RTSP with auth**: If URL has user:pass, ensure compose.yml handles it (currently open)

## RTSP URL Formats Reference

| Stream Type | URL Format | Example |
|-------------|-----------|---------|
| **H264 Native** | `rtsp://IP:PORT/h264_stream` | `rtsp://192.168.1.50:8080/h264_stream` |
| **H264 MJPEG** | `rtsp://IP:PORT/h264_mjpeg` | `rtsp://192.168.1.50:8080/h264_mjpeg` |
| **MJPEG Stream** | `rtsp://IP:PORT/video` | `rtsp://192.168.1.50:8081/video` |
| **Standard RTSP** | `rtsp://IP:PORT/stream` | `rtsp://192.168.1.50:554/stream1` |
| **With Authentication** | `rtsp://user:pass@IP:PORT/stream` | `rtsp://admin:password@192.168.1.50:554/stream` |

## System Architecture Flow

```
┌─────────────┐     RTSP Stream     ┌─────────────────┐
│  Mobile     │ ────────────────→ │  CV Service     │
│  IP Camera  │                     │ (Docker Container)│
└─────────────┘                     │ • YOLO Detection│
                                  │ • ByteTrack     │
                                  │ • Floor Mapping │
                                      ↓                 ┌─────────────────┐
                                      │                 │  Redis          │
                                      │  Floor Coordinates│ • Real-time Data│
                                      │                 │   Buffering     │
                                      ↓                 └─────────────────┘
┌─────────────────┐                 ┌─────────────────┐
│  Backend API    │ ←──── WebSocket ─│  PostgreSQL     │
│ (FastAPI)       │   Alerts & History│   (History)     │
└─────────────────┘                 └─────────────────┘
                                      ↓
                              ┌─────────────────┐
                              │  Frontend       │
                              │ (React + Three.js)│
                              │  3D Digital Twin │
                              └─────────────────┘
```

## Production Considerations

### Before Deploying:
- [ ] Change default passwords from `.env.example`
- [ ] Test RTSP URL extensively with VLC
- [ ] Calibrate floor coordinates accurately
- [ ] Ensure adequate lighting in camera view
- [ ] Mount camera securely in fixed position
- [ ] Test person detection with multiple people
- [ ] Verify alert thresholds in backend code
- [ ] Set up regular calibration checks (camera may drift)

### Monitoring:
- Check `docker compose ps` daily
- Review `docker compose logs cv` for errors
- Monitor PostgreSQL storage growth (10Hz snapshots)
- Redis memory usage for real-time buffering

## Quick Start Summary

```powershell
# 1. Find RTSP URL from your phone's IP camera app
#    (e.g., IP Webcam: rtsp://192.168.1.50:8080/h264_stream)

# 2. Update .env
cd C:\Users\abhij\OneDrive\source\BE_Project_main\twin3d
# Edit .env, set CAM01_URL=rtsp://YOUR_IP:PORT/STREAM_PATH

# 3. Start CV profile
docker compose --profile cv up -d --build

# 4. Verify
docker compose ps          # Check running
docker compose logs cv -f  # Watch connection

# 5. Access frontend
http://localhost:5173      # View person detection

# 6. Calibrate (first time only)
python -m cv_service.calibrate --image frame.jpg --world "2,2;10,2;10,8;2,8" --out calib/cam01.json
```

---

*Documentation generated for BE_Project_main/twin3d IP Camera Integration*
*Last updated: November 2026*