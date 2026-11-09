"""One camera: RTSP/HTTP -> YOLO + Tracker -> foot point -> homography (metres) -> Redis.

  python -m cv_service.worker --cam cam01 --url rtsp://... --calib calib/cam01.json
Publishes M1's contract (docs/contracts/tracks_v1.md) to stream tracks:{cam}.
"""
import argparse, json, os, pathlib, threading, time
import cv2
import numpy as np
import redis

# Patch pathlib.Path.exists to avoid Windows PermissionError on git check in ultralytics
_orig_exists = pathlib.Path.exists
def _safe_exists(self, *args, **kwargs):
    try:
        return _orig_exists(self, *args, **kwargs)
    except (PermissionError, OSError):
        return False
pathlib.Path.exists = _safe_exists

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class SimpleTracker:
    """Lightweight Euclidean centroid tracker used as fallback if lap/ByteTrack is unavailable."""
    def __init__(self, max_dist=100.0, max_missing=10):
        self.next_id = 1
        self.tracks = {}  # tid -> (cx, cy, missing_count)

    def update(self, centers):
        assigned_ids = []
        if not self.tracks:
            for cx, cy in centers:
                self.tracks[self.next_id] = (cx, cy, 0)
                assigned_ids.append(self.next_id)
                self.next_id += 1
            return assigned_ids

        # Match existing tracks to nearest new center
        tids = list(self.tracks.keys())
        used_centers = set()
        for tid in tids:
            tx, ty, missing = self.tracks[tid]
            best_idx, best_dist = None, float("inf")
            for idx, (cx, cy) in enumerate(centers):
                if idx in used_centers:
                    continue
                d = np.hypot(tx - cx, ty - cy)
                if d < best_dist and d <= 150.0:
                    best_dist, best_idx = d, idx
            if best_idx is not None:
                used_centers.add(best_idx)
                self.tracks[tid] = (centers[best_idx][0], centers[best_idx][1], 0)

        # Allocate IDs in order of centers
        for idx, (cx, cy) in enumerate(centers):
            # Find if matched to a tid
            matched_tid = None
            for tid, (tx, ty, _) in self.tracks.items():
                if tx == cx and ty == cy:
                    matched_tid = tid
                    break
            if matched_tid is None:
                matched_tid = self.next_id
                self.tracks[matched_tid] = (cx, cy, 0)
                self.next_id += 1
            assigned_ids.append(matched_tid)

        # Clean old tracks
        for tid in list(self.tracks.keys()):
            if tid not in assigned_ids:
                tx, ty, missing = self.tracks[tid]
                if missing + 1 > 10:
                    del self.tracks[tid]
                else:
                    self.tracks[tid] = (tx, ty, missing + 1)
        return assigned_ids


class Grabber(threading.Thread):
    """Reads frames continuously, keeps only the newest (no latency build-up), reconnects with back-off."""

    def __init__(self, url: str):
        super().__init__(daemon=True)
        self.url, self.frame, self.ts, self.lock = url, None, 0.0, threading.Lock()
        self.alive = True
        self.connected = False

    def run(self):
        backoff = 1
        while self.alive:
            print(f"[Camera Grabber] Connecting to stream: {self.url} ...")
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                print(f"[Camera Grabber] Cannot open stream at {self.url}. Retrying in {backoff}s...")
                self.connected = False
                time.sleep(backoff)
                backoff = min(backoff * 2, 15)
                continue

            print(f"[Camera Grabber] Stream successfully connected: {self.url}")
            self.connected = True
            backoff, last_ok = 1, time.time()
            while self.alive:
                ok, f = cap.read()
                if ok:
                    last_ok = time.time()
                    with self.lock:
                        self.frame, self.ts = f, last_ok
                elif time.time() - last_ok > 5:
                    print(f"[Camera Grabber] Stream timed out after 5s without frames.")
                    break
            cap.release()
            self.connected = False

    def latest(self):
        with self.lock:
            f, t = self.frame, self.ts
            self.frame = None
        return f, t


def to_world(H: np.ndarray, px: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(px.reshape(1, -1, 2).astype(np.float32), H)[0]


def find_default_model(model_arg: str) -> str:
    if os.path.exists(model_arg):
        return model_arg
    candidates = [
        "yolo26n.pt",
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "yolo26n.pt"),
        "yolov8n.pt",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return model_arg


def get_homography(calib_path: str) -> np.ndarray:
    if os.path.exists(calib_path):
        try:
            return np.array(json.load(open(calib_path))["H"], dtype=np.float64)
        except Exception as e:
            print(f"[Calibration] Warning reading {calib_path}: {e}")
    # Default homography: map 1920x1080 frame to 0..20m x 0..15m on floor
    px = np.array([[0, 0], [1920, 0], [1920, 1080], [0, 1080]], dtype=np.float32)
    world = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 15.0], [0.0, 15.0]], dtype=np.float32)
    H, _ = cv2.findHomography(px, world)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="cam01")
    ap.add_argument("--url", default=os.getenv("CAM01_URL", "http://192.168.43.184:8080/video"))
    ap.add_argument("--calib", default="calib/cam01.json")
    ap.add_argument("--redis", default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--model", default="yolo26n.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--floor-w", type=float, default=40.0)
    ap.add_argument("--floor-h", type=float, default=25.0)
    a = ap.parse_args()

    model_path = find_default_model(a.model)
    print(f"[Worker] Loading YOLO model from {model_path}...")
    from ultralytics import YOLO
    model = YOLO(model_path)

    H = get_homography(a.calib)
    print(f"[Worker] Homography loaded. Connecting to Redis: {a.redis}...")
    r = redis.from_url(a.redis, decode_responses=True)
    
    grab = Grabber(a.url)
    grab.start()
    
    fallback_tracker = SimpleTracker()
    ema: dict[int, tuple[float, float]] = {}
    frame_no, last_hb, n_fps, t_fps = 0, 0.0, 0, time.time()
    fps_meas = 0.0

    print(f"[Worker] Starting detection loop for camera {a.cam} at target {a.fps} FPS...")
    while True:
        t0 = time.time()
        frame, cap_ts = grab.latest()
        if frame is None:
            if t0 - last_hb > 5:
                status = "online" if grab.connected else "offline"
                r.xadd("camstatus", {"d": json.dumps({"cam": a.cam, "state": status, "fps": 0, "ts": t0})}, maxlen=500)
                last_hb = t0
            time.sleep(0.05)
            continue

        # Run detection & tracking
        ids, xyxy, conf = [], [], []
        try:
            res = model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml",
                              conf=a.conf, iou=0.5, imgsz=a.imgsz, verbose=False)[0]
            if res.boxes is not None:
                xyxy = res.boxes.xyxy.cpu().numpy()
                conf = res.boxes.conf.cpu().numpy()
                if res.boxes.id is not None:
                    ids = res.boxes.id.int().cpu().tolist()
        except Exception:
            # Fallback to model.predict + SimpleTracker
            res = model.predict(frame, classes=[0], conf=a.conf, imgsz=a.imgsz, verbose=False)[0]
            if res.boxes is not None:
                xyxy = res.boxes.xyxy.cpu().numpy()
                conf = res.boxes.conf.cpu().numpy()

        if len(xyxy) > 0 and len(ids) != len(xyxy):
            centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in xyxy]
            ids = fallback_tracker.update(centers)

        objs = []
        if len(xyxy) > 0:
            feet = np.stack([(xyxy[:, 0] + xyxy[:, 2]) / 2, xyxy[:, 3]], axis=1)  # bottom-centre
            world = to_world(H, feet)
            for tid, (x, y), c, b in zip(ids, world, conf, xyxy):
                if not (0 <= x <= a.floor_w and 0 <= y <= a.floor_h):
                    continue  # outside floor bounds
                px, py = ema.get(tid, (x, y))
                x, y = 0.5 * x + 0.5 * px, 0.5 * y + 0.5 * py  # EMA alpha=0.5
                ema[tid] = (x, y)
                objs.append({
                    "tid": int(tid),
                    "x": round(float(x), 2),
                    "y": round(float(y), 2),
                    "conf": round(float(c), 2),
                    "bbox": [int(v) for v in b]
                })

        r.xadd(
            f"tracks:{a.cam}",
            {"d": json.dumps({"v": 1, "cam": a.cam, "ts": cap_ts, "frame": frame_no, "objs": objs})},
            maxlen=5000,
            approximate=True
        )
        frame_no += 1
        n_fps += 1
        if t0 - t_fps >= 5:
            fps_meas, n_fps, t_fps = n_fps / (t0 - t_fps), 0, t0
        if t0 - last_hb > 5:
            r.xadd("camstatus", {"d": json.dumps({"cam": a.cam, "state": "online", "fps": round(fps_meas, 1), "ts": t0})}, maxlen=500)
            last_hb = t0

        time.sleep(max(0.0, 1 / a.fps - (time.time() - t0)))


if __name__ == "__main__":
    main()
