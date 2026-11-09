"""Twin3D API: Redis ingest -> world state -> WebSocket snapshots (+ batched DB writes)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import orjson
    def dumps(obj) -> str:
        return orjson.dumps(obj).decode()
    loads = orjson.loads
except ImportError:
    import json
    def dumps(obj) -> str:
        return json.dumps(obj)
    loads = json.loads
import redis.asyncio as aioredis
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from .alerts import AlertEngine, Zone

log = logging.getLogger("twin3d")
logging.basicConfig(level=logging.INFO)

CAMERAS = [c for c in os.getenv("CAMERAS", "cam01,cam02,cam03,cam04").split(",") if c]
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "")
STALE_S = 3.0
STORE_INTERVAL_S = 0.5  # 2 Hz history per person

CONFIG = json.loads((Path(__file__).parent / "data" / "floor_f1.json").read_text())
FLOOR_ID = CONFIG["floor"]["id"]
engine = AlertEngine([Zone(**z) for z in CONFIG["zones"]])


class Hub:
    """Fan-out with bounded per-client queues: slow clients lose old snapshots, never block."""

    def __init__(self):
        self.clients: set[asyncio.Queue] = set()
        self.dropped = 0

    def add(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5)
        self.clients.add(q)
        return q

    def remove(self, q: asyncio.Queue):
        self.clients.discard(q)

    def publish(self, payload: str):
        for q in self.clients:
            if q.full():
                try:
                    q.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(payload)


hub = Hub()
world: dict[int, list] = {}          # id -> [x, y, arrival_ts, cam]
last_store: dict[int, float] = {}
cam_state: dict[str, dict] = {c["id"]: {**c, "state": "unknown", "fps": 0.0, "last_seen": 0.0}
                              for c in CONFIG["cameras"] if c["id"] in CAMERAS}
alert_log: list[dict] = []
alert_seq = 0
pos_buffer: list[tuple] = []
pool = None


def emit_alert(a: dict):
    global alert_seq
    alert_seq += 1
    a["id"] = alert_seq
    alert_log.append(a)
    del alert_log[:-200]
    hub.publish(dumps(a))


def set_cam(cam: str, state: str, fps: float = 0.0):
    c = cam_state.setdefault(cam, {"id": cam, "name": cam, "state": "unknown", "fps": 0.0, "last_seen": 0.0})
    changed = c["state"] != state
    c.update(state=state, fps=fps, last_seen=time.time())
    if changed:
        hub.publish(dumps({"t": "cam", "cam": cam, "state": state, "fps": fps, "ts": time.time()}))
        if state == "offline":
            emit_alert({"t": "alert", "type": "camera_offline", "zone": cam, "tid": None,
                        "ts": time.time(), "severity": "medium"})


def handle_tracks(cam: str, msg: dict):
    now = time.time()
    cam_idx = CAMERAS.index(cam) if cam in CAMERAS else 0
    for o in msg.get("objs", []):
        pid = o.get("gid", cam_idx * 100_000 + o["tid"])
        world[pid] = [o["x"], o["y"], now, cam]
        if now - last_store.get(pid, 0) >= STORE_INTERVAL_S:
            last_store[pid] = now
            pos_buffer.append((datetime.fromtimestamp(msg["ts"], timezone.utc), cam, pid,
                               float(o["x"]), float(o["y"]), float(o.get("conf", 0))))
    if cam_state.get(cam, {}).get("state") != "online":
        set_cam(cam, "online", cam_state.get(cam, {}).get("fps", 0.0))
    cam_state[cam]["last_seen"] = now


async def ingest_loop(r: aioredis.Redis):
    cursors = {f"tracks:{c}": "$" for c in CAMERAS}
    cursors["camstatus"] = "$"
    while True:
        try:
            resp = await r.xread(cursors, count=500, block=100)
            for stream, msgs in resp or []:
                for mid, fields in msgs:
                    cursors[stream] = mid
                    msg = loads(fields["d"])
                    if stream == "camstatus":
                        set_cam(msg["cam"], msg.get("state", "online"), msg.get("fps", 0.0))
                    else:
                        handle_tracks(stream.split(":", 1)[1], msg)
        except (aioredis.ConnectionError, OSError):
            log.warning("Redis is not running at %s. Waiting to connect...", REDIS_URL)
            await asyncio.sleep(2)
        except Exception:
            log.exception("ingest error; retrying")
            await asyncio.sleep(2)


async def broadcast_loop():
    tick = 0
    while True:
        await asyncio.sleep(0.1)
        now = time.time()
        for pid in [p for p, v in world.items() if now - v[2] > STALE_S]:
            del world[pid]
        people = [[pid, round(v[0], 2), round(v[1], 2)] for pid, v in world.items()]
        hub.publish(dumps({"t": "snap", "ts": now, "floor": FLOOR_ID, "people": people}))
        tick += 1
        if tick % 5 == 0:
            for a in engine.evaluate([(p[0], p[1], p[2]) for p in people], now):
                emit_alert(a)
        if tick % 20 == 0:
            for cam, c in cam_state.items():
                if c["state"] == "online" and now - c["last_seen"] > 15:
                    set_cam(cam, "offline")


async def flush_loop():
    while True:
        await asyncio.sleep(1.0)
        if not pos_buffer or pool is None:
            pos_buffer.clear() if pool is None else None
            continue
        batch, pos_buffer[:] = pos_buffer[:], []
        try:
            async with pool.acquire() as conn:
                await conn.copy_records_to_table(
                    "positions", records=batch, columns=["ts", "cam", "gid", "x", "y", "conf"])
        except Exception:
            log.exception("DB flush failed; %d rows dropped", len(batch))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    if DATABASE_URL:
        try:
            import importlib
            asyncpg = importlib.import_module("asyncpg")
            pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
        except Exception:
            log.warning("PostgreSQL unavailable or asyncpg not installed; running without history")
    tasks = [asyncio.create_task(f()) for f in (lambda: ingest_loop(r), broadcast_loop, flush_loop)]
    yield
    for t in tasks:
        t.cancel()
    await r.aclose()
    if pool:
        await pool.close()


app = FastAPI(title="Twin3D API", lifespan=lifespan)
api = APIRouter(prefix="/api")


@api.get("/health")
async def health():
    return {"status": "ok", "people": len(world), "ws_clients": len(hub.clients),
            "ws_dropped": hub.dropped, "db": pool is not None}


@api.get("/floor")
async def floor():
    return CONFIG["floor"]


@api.get("/zones")
async def zones():
    return CONFIG["zones"]


@api.get("/cameras")
async def cameras():
    return list(cam_state.values())


@api.get("/alerts")
async def alerts():
    return list(reversed(alert_log))


app.include_router(api)


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    q = hub.add()
    for c in cam_state.values():
        await ws.send_text(dumps({"t": "cam", "cam": c["id"], "state": c["state"], "fps": c["fps"], "ts": time.time()}))

    async def sender():
        while True:
            await ws.send_text(await q.get())

    send_task = asyncio.create_task(sender())
    recv_task = asyncio.create_task(ws.receive_text())
    try:
        await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        recv_task.cancel()
        hub.remove(q)
