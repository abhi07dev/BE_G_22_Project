# Contract: tracks v1 (CV to backend)

Owner: Member 1. Consumers: Member 2 (backend), Member 3 (fake data). Any change bumps `v` and needs sign-off from all.

Redis Stream `tracks:{cam}`; each entry has ONE field `d` holding this JSON:

```json
{"v":1,"cam":"cam01","ts":1735000000.123,"frame":1042,
 "objs":[{"tid":17,"x":12.43,"y":5.87,"conf":0.81,"bbox":[412,220,470,390]}]}
```

- `x`,`y`: metres, floor coordinate system (see coordinates.md).
- `ts`: capture time, UTC seconds (float).
- `gid` (optional, per object): global ID once fusion exists (Stage 3). Backend uses `gid` when present, otherwise `cam_index*100000 + tid`.
- Heartbeat every 5 s to stream `camstatus`, field `d` = `{"cam","state":"online|degraded|offline","fps","ts"}`.

# Contract: WebSocket `/ws/live` (backend to frontend)

```json
{"t":"snap","ts":1735000000.2,"floor":"F1","people":[[17,12.43,5.87]]}
{"t":"cam","cam":"cam01","state":"offline","fps":0,"ts":1735000001.0}
{"t":"alert","id":991,"type":"zone_enter","zone":"Server room","tid":17,"ts":1735000002.4,"severity":"high"}
```
Snapshots every 100 ms. Slow clients lose old snapshots (bounded queue of 5), never block others.
