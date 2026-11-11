"""Zone alert rules (MVP: restricted-zone entry, occupancy limit)."""
from __future__ import annotations

import time
from dataclasses import dataclass


def point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    if not poly or len(poly) < 3:
        return False
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


@dataclass
class Zone:
    id: int
    name: str
    type: str
    polygon: list[list[float]]
    max_occupancy: int | None = None


class AlertEngine:
    def __init__(self, zones: list[Zone], cooldown: float = 60.0):
        self.zones = zones
        self.cooldown = cooldown
        self._last: dict[tuple, float] = {}

    def _due(self, key: tuple, now: float) -> bool:
        if len(self._last) > 1000:
            cutoff = now - (self.cooldown * 2)
            self._last = {k: v for k, v in self._last.items() if v >= cutoff}
        if now - self._last.get(key, -1e12) >= self.cooldown:
            self._last[key] = now
            return True
        return False

    def evaluate(self, people: list[tuple[int, float, float]], now: float | None = None) -> list[dict]:
        """people: (id, x, y). Returns alert dicts (without ids)."""
        now = time.time() if now is None else now
        out: list[dict] = []
        for z in self.zones:
            inside = [p for p in people if point_in_polygon(p[1], p[2], z.polygon)]
            if z.type == "restricted":
                for pid, _, _ in inside:
                    if self._due((pid, z.id), now):
                        out.append({"t": "alert", "type": "zone_enter", "zone": z.name,
                                    "tid": pid, "ts": now, "severity": "high"})
            if z.max_occupancy and len(inside) > z.max_occupancy:
                if self._due(("occ", z.id), now):
                    out.append({"t": "alert", "type": "occupancy_exceeded", "zone": z.name,
                                "tid": None, "ts": now, "severity": "medium",
                                "count": len(inside)})
        return out
