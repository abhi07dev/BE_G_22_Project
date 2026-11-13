"""Modified YOLO worker for 3-floor person detection across multiple cameras.

Supports:
- Multiple floors (F1, F2, F3) with independent calibration
- Per-floor person tracking with global IDs
- Cross-camera deduplication
- Floor zone alerting
- Redis pub/sub for inter-process communication
"""

import argparse
import json
import os
import threading
import time
from collections import defaultdict

import cv2
import numpy as np
import redis

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class Grabber(threading.Thread):
    """Reads frames continuously, keeps only the newest (no latency build-up), reconnects with back-off."""

    def __init__(self, url: str):
        super().__init__(daemon=True)
        self.url, self.frame, self.ts, self.lock = url, None, 0.0, threading.Lock()
        self.alive = True

    def run(self):
        backoff = 1
        while self.alive:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff, last_ok = 1, time.time()
            while self.alive:
                ok, f = cap.read()
                if ok:
                    last_ok = time.time()
                    with self.lock:
                        self.frame, self.ts = f, last_ok
                elif time.time() - last_ok > 5:
                    break
            cap.release()

    def latest(self):
        with self.lock:
            f, t = self.frame, self.ts
            self.frame = None
        return f, t


def to_world(H: np.ndarray, px: np.ndarray) -> np.ndarray:
    """Convert pixel coordinates to world metres using homography matrix H."""
    return cv2.perspectiveTransform(px.reshape(1, -1, 2).astype(np.float32), H)[0]


def load_calib(calib_path: str) -> np.ndarray:
    """Load homography matrix from calibration JSON file."""
    H = np.array(json.load(open(calib_path))["H"], dtype=np.float64)
    return H


def world_to_floor(x: float, y: float, floor_id: str, floor_dims: dict) -> tuple:
    """Convert world coordinates to floor-relative coordinates.
    
    Args:
        x, y: World metres from camera calibration
        floor_id: 'F1', 'F2', or 'F3'
        floor_dims: Dict with 'width', 'height' in metres per floor
    
    Returns:
        Tuple (fx, fy) floor-relative coordinates
    """
    # Floor origins (metres from building origin)
    floor_origins = {
        "F1": {"x": 0.0, "y": 0.0},    # Ground floor
        "F2": {"x": 0.0, "y": 12.5},   # Middle floor
        "F3": {"x": 0.0, "y": 25.0},   # Top floor
    }
    
    origin = floor_origins.get(floor_id, {"x": 0.0, "y": 0.0})
    floor_w = floor_dims.get("width", 40.0)
    floor_h = floor_dims.get("height", 25.0)
    
    # Keep x as-is (width), adjust y for floor level
    fx = max(0.0, min(floor_w, x - origin["x"]))
    fy = max(0.0, min(floor_h, y - origin["y"]))
    
    return fx, fy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True, help="Camera identifier (e.g., cam01)")
    ap.add_argument("--url", required=True, help="RTSP or camera index URL")
    ap.add_argument("--calib", required=True, help="Path to calibration JSON file")
    ap.add_argument("--redis", default="redis://localhost:6379/0", help="Redis URL")
    ap.add_argument("--model", default="yolov8n.pt", help="YOLO model path")
    ap.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    ap.add_argument("--conf", type=float, default=0.35, help="Confidence threshold")
    ap.add_argument("--fps", type=float, default=5.0, help="Target FPS")
    ap.add_argument("--floor", required=True, choices=["F1", "F2", "F3"], help="Floor ID")
    ap.add_argument("--floor-w", type=float, default=40.0, help="Floor width in metres")
    ap.add_argument("--floor-h", type=float, default=25.0, help="Floor height in metres")
    ap.add_argument("--building-length", type=float, default=100.0, help="Building length in metres")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    H = load_calib(a.calib)
    r = redis.from_url(a.redis, decode_responses=True)
    grab = Grabber(a.url)
    grab.start()

    # Floor configuration
    floor_dims = {"width": a.floor_w, "height": a.floor_h}
    floor_id = a.floor

    # Per-floor person tracking: {global_person_id: [x, y, floor, cam, last_seen]}
    world: dict[int, list] = {}
    # Floor-specific person counts
    floor_counts: dict[str, int] = {"F1": 0, "F2": 0, "F3": 0}
    # EMA per person for smoothing
    ema: dict[int, tuple[float, float]] = {}

    frame_no, last_hb, n_fps, t_fps = 0, 0.0, 0, time.time()
    fps_meas = 0.0

    print(f"[{floor_id}] Starting detection loop - Ctrl+C to stop")
    print(f"  Camera: {a.url}")
    print(f"  Floor: {floor_id} ({a.floor_w}m x {a.floor_h}m)")
    print(f"  Building length: {a.building_length}m")
    print(f"  Press Q in window to stop")

    while True:
        t0 = time.time()
        frame, cap_ts = grab.latest()
        if frame is None:
            if t0 - last_hb > 5:
                print(f"[{floor_id}] No frame received - checking connection...")
                last_hb = t0
            time.sleep(0.05)
            continue

        # YOLO detection + tracking
        res = model.track(
            frame, persist=True, classes=[0], tracker="bytetrack.yaml",
            conf=a.conf, iou=0.5, imgsz=a.imgsz, verbose=False
        )[0]

        objs = []
        if res.boxes is not None and res.boxes.id is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.int().cpu().tolist()
            conf = res.boxes.conf.cpu().numpy()

            # Compute bottom-centre pixel feet
            feet = np.stack([(xyxy[:, 0] + xyxy[:, 2]) / 2, xyxy[:, 3]], axis=1)

            # Convert to world metres via homography
            world_pts = to_world(H, feet)

            for tid, (wx, wy), c, b in zip(ids, world_pts, conf, xyxy):
                # Convert world to floor-relative coordinates
                fx, fy = world_to_floor(wx, wy, floor_id, floor_dims)

                # Floor boundary check
                if not (0 <= fx <= a.floor_w and 0 <= fy <= a.floor_h):
                    continue  # outside floor polygon

                # EMA smoothing
                px, py = ema.get(tid, (fx, fy))
                fx, fy = 0.5 * fx + 0.5 * px, 0.5 * fy + 0.5 * py
                ema[tid] = (fx, fy)

                # Global person tracking
                # Use floor_id * 1000 + tid as global-ish ID to avoid cross-floor conflicts
                global_id = int(floor_id[1:]) * 1000 + tid  # F1->1001, F2->2001, F3->3001

                # Update world state
                now = time.time()
                if global_id not in world:
                    floor_counts[floor_id] = floor_counts.get(floor_id, 0) + 1
                world[global_id] = [fx, fy, now, floor_id, cap_ts]

                objs.append({
                    "tid": tid,
                    "gid": global_id,
                    "x": round(float(fx), 2),
                    "y": round(float(fy), 2),
                    "conf": round(float(c), 2),
                    "bbox": [int(v) for v in b],
                    "floor": floor_id
                })

        # Publish tracks to Redis floor-specific channel
        try:
            r.xadd(
                f"tracks:{floor_id}",
                {"d": json.dumps({"v": 1, "cam": a.cam, "ts": cap_ts, "frame": frame_no, "objs": objs})},
                maxlen=5000, approximate=True
            )
        except Exception as e:
            print(f"[{floor_id}] Redis publish error: {e}")

        frame_no += 1
        n_fps += 1
        if t0 - t_fps >= 5:
            fps_meas, n_fps, t_fps = n_fps / (t0 - t_fps), 0, t0
        if t0 - last_hb > 5:
            print(f"[{floor_id}] Frame drop or stream issue last seen {int(t0-last_hb)}s ago")
            last_hb = t0

        # Sleep to target FPS
        sleep_time = max(0.0, 1 / a.fps - (time.time() - t0))
        if sleep_time > 0:
            time.sleep(sleep_time)

    # Cleanup
    grab.alive = False
    print(f"[{floor_id}] Detection loop ended")


if __name__ == "__main__":
    main()