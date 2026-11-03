# Twin3D: AI-based 3D digital twin surveillance

Existing CCTV cameras -> YOLO + ByteTrack -> floor coordinates (metres) -> Redis -> FastAPI -> WebSocket -> React + Three.js digital twin.

## Run the demo (no cameras needed)

```bash
cp .env.example .env        # set a real POSTGRES_PASSWORD
make demo                   # postgres, redis, api, frontend, fake producer (200 people)
```
Open http://localhost:5173 (API docs: http://localhost:8000/docs). People walking into the red zones raise alerts.

Without Docker: `pip install -r backend/requirements.txt`, run Redis, `uvicorn app.main:app` in `backend/`, `python tools/fake_producer.py`, then `npm install && npm run dev` in `frontend/`.

## Run with a real camera

1. Grab one frame, measure 4+ floor points, then:
   `python -m cv_service.calibrate --image frame.jpg --world "2,2;10,2;10,8;2,8" --out calib/cam01.json`
2. Set `CAM01_URL` in `.env`, then `docker compose --profile cv up -d` (or run `python -m cv_service.worker ...` directly; GPU recommended).

## Layout

| Path | Owner | Purpose |
|---|---|---|
| `cv/` | Member 1 | RTSP ingest, detection, tracking, calibration |
| `backend/` | Member 2 | Ingest, world state, alerts, WebSocket, history |
| `frontend/` | Member 3 | 3D twin, alert panel |
| `tools/`, `compose.yml`, `.github/` | Member 4 | Simulators, Docker, CI, load tests |
| `docs/contracts/` | All | Message formats; change only with team sign-off |

## What exists vs. what the plan adds

Done in this scaffold: Redis ingest, 10 Hz snapshots, bounded fan-out, zone and occupancy alerts with cooldown, camera offline detection, batched 2 Hz history to PostgreSQL, 3D scene with instanced people, alert panel, CV worker, calibration tool, CI.
Planned per the 26-week guides: auth and roles (Stage 2), replay and heatmap APIs (Stage 3), delta snapshots, Web Worker parsing, TensorRT, load tests to 1,000+ (Stage 4), HTTPS, security scans, failure drills (Stage 5).
