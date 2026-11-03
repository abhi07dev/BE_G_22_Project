"""One camera: RTSP/file -> YOLO + ByteTrack -> foot point -> homography (metres) -> Redis.

  python -m cv_service.worker --cam cam01 --url rtsp://... --calib calib/cam01.json
Publishes M1's contract (docs/contracts/tracks_v1.md) to stream tracks:{cam}.
"""
import argparse, json, os, threading, time
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
    return cv2.perspectiveTransform(px.reshape(1, -1, 2).astype(np.float32), H)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--redis", default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--floor-w", type=float, default=40.0)
    ap.add_argument("--floor-h", type=float, default=25.0)
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    H = np.array(json.load(open(a.calib))["H"], dtype=np.float64)
    r = redis.from_url(a.redis, decode_responses=True)
    grab = Grabber(a.url)
    grab.start()
    ema: dict[int, tuple[float, float]] = {}
    frame_no, last_hb, n_fps, t_fps = 0, 0.0, 0, time.time()
    fps_meas = 0.0

    while True:
        t0 = time.time()
        frame, cap_ts = grab.latest()
        if frame is None:
            if t0 - last_hb > 5:
                r.xadd("camstatus", {"d": json.dumps({"cam": a.cam, "state": "offline", "fps": 0, "ts": t0})}, maxlen=500)
                last_hb = t0
            time.sleep(0.05)
            continue
        res = model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml",
                          conf=a.conf, iou=0.5, imgsz=a.imgsz, verbose=False)[0]
        objs = []
        if res.boxes is not None and res.boxes.id is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            ids = res.boxes.id.int().cpu().tolist()
            conf = res.boxes.conf.cpu().numpy()
            feet = np.stack([(xyxy[:, 0] + xyxy[:, 2]) / 2, xyxy[:, 3]], axis=1)  # bottom-centre
            world = to_world(H, feet)
            for tid, (x, y), c, b in zip(ids, world, conf, xyxy):
                if not (0 <= x <= a.floor_w and 0 <= y <= a.floor_h):
                    continue  # outside floor polygon: reflections, posters
                px, py = ema.get(tid, (x, y))
                x, y = 0.5 * x + 0.5 * px, 0.5 * y + 0.5 * py  # EMA alpha=0.5
                ema[tid] = (x, y)
                objs.append({"tid": tid, "x": round(float(x), 2), "y": round(float(y), 2),
                             "conf": round(float(c), 2), "bbox": [int(v) for v in b]})
        r.xadd(f"tracks:{a.cam}", {"d": json.dumps({"v": 1, "cam": a.cam, "ts": cap_ts, "frame": frame_no, "objs": objs})},
               maxlen=5000, approximate=True)
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
