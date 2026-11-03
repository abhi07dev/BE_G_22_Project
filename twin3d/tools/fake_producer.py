"""Simulates N people walking a floor and publishes M1's contract (tracks:{cam}, camstatus) to Redis.
Lets backend and frontend work before the CV pipeline exists.  Usage:
  python tools/fake_producer.py --people 200 --cams 4 --hz 10 [--redis redis://localhost:6379/0]
"""
import argparse, json, math, random, time
import redis

W, H = 40.0, 25.0
CAM_POS = [(2, 2), (38, 2), (2, 23), (38, 23)]


def nearest_cam(x, y, ncams):
    return min(range(ncams), key=lambda i: (x - CAM_POS[i % 4][0]) ** 2 + (y - CAM_POS[i % 4][1]) ** 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis", default="redis://localhost:6379/0")
    ap.add_argument("--people", type=int, default=200)
    ap.add_argument("--cams", type=int, default=4)
    ap.add_argument("--hz", type=float, default=10)
    a = ap.parse_args()
    r = redis.from_url(a.redis, decode_responses=True)
    people = [{"x": random.uniform(0, W), "y": random.uniform(0, H),
               "h": random.uniform(0, 2 * math.pi), "v": random.uniform(0.8, 1.6)} for _ in range(a.people)]
    dt, frame, last_hb = 1 / a.hz, 0, 0.0
    while True:
        t0 = time.time()
        per_cam = {i: [] for i in range(a.cams)}
        for gid, p in enumerate(people):
            p["h"] += random.gauss(0, 0.25)
            nx, ny = p["x"] + math.cos(p["h"]) * p["v"] * dt, p["y"] + math.sin(p["h"]) * p["v"] * dt
            if not (0 <= nx <= W and 0 <= ny <= H):
                p["h"] += math.pi
                nx, ny = min(max(nx, 0), W), min(max(ny, 0), H)
            p["x"], p["y"] = nx, ny
            c = nearest_cam(nx, ny, a.cams)
            per_cam[c].append({"tid": gid, "gid": gid, "x": round(nx, 2), "y": round(ny, 2), "conf": 0.8})
        for i, objs in per_cam.items():
            msg = {"v": 1, "cam": f"cam{i+1:02d}", "ts": t0, "frame": frame, "objs": objs}
            r.xadd(f"tracks:cam{i+1:02d}", {"d": json.dumps(msg)}, maxlen=5000, approximate=True)
        if t0 - last_hb > 5:
            for i in range(a.cams):
                r.xadd("camstatus", {"d": json.dumps({"cam": f"cam{i+1:02d}", "state": "online", "fps": a.hz, "ts": t0})}, maxlen=500)
            last_hb = t0
        frame += 1
        time.sleep(max(0.0, dt - (time.time() - t0)))


if __name__ == "__main__":
    main()
