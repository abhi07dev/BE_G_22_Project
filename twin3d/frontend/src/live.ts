import { live, useUI, Alert, Zone } from "./store";

function inPoly(x: number, y: number, poly: [number, number][]) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export async function loadStatic() {
  const [floor, zones, cams, alerts] = await Promise.all(
    ["floor", "zones", "cameras", "alerts"].map((p) => fetch(`/api/${p}`).then((r) => r.json()))
  );
  useUI.setState({
    floor, zones,
    cams: Object.fromEntries(cams.map((c: any) => [c.id, c])),
    alerts,
  });
}

export function connect() {
  let delay = 500;
  const open = () => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/live`);
    ws.onopen = () => { delay = 500; useUI.setState({ conn: "live" }); };
    ws.onclose = () => {
      useUI.setState({ conn: "offline" });
      setTimeout(open, delay);
      delay = Math.min(delay * 2, 8000);
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.t === "snap") {
        const now = performance.now() / 1000;
        const restricted: Zone[] = useUI.getState().zones.filter((z) => z.type === "restricted");
        for (const [id, x, y] of m.people as [number, number, number][]) {
          const p = live.people.get(id);
          const red = restricted.some((z) => inPoly(x, y, z.polygon));
          if (p) { p.tx = x; p.ty = y; p.seen = now; p.red = red; }
          else live.people.set(id, { x, y, tx: x, ty: y, seen: now, red });
        }
      } else if (m.t === "cam") {
        useUI.setState((s) => ({ cams: { ...s.cams, [m.cam]: { ...(s.cams[m.cam] ?? { id: m.cam, name: m.cam, x: 0, y: 0 }), state: m.state, fps: m.fps } } }));
      } else if (m.t === "alert") {
        useUI.setState((s) => ({ alerts: [m as Alert, ...s.alerts].slice(0, 100) }));
      }
    };
  };
  open();
  setInterval(() => useUI.setState({ count: live.people.size }), 500);
}
