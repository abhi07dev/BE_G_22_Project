import { useEffect } from "react";
import Scene from "./Scene";
import { connect, loadStatic } from "./live";
import { useUI } from "./store";

function ago(ts: number) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}

const LABEL: Record<string, string> = {
  zone_enter: "Entered restricted zone",
  occupancy_exceeded: "Occupancy limit exceeded",
  camera_offline: "Camera offline",
};

export default function App() {
  const { conn, count, cams, alerts, view, floor } = useUI();
  useEffect(() => { loadStatic().then(connect); }, []);
  return (
    <div className="app">
      <main className="stage"><Scene /></main>
      <aside className="panel">
        <header>
          <p className="floor">{floor.name}</p>
          <p className={`conn ${conn}`}>{conn === "live" ? "Receiving live data" : conn === "connecting" ? "Connecting" : "Disconnected, retrying"}</p>
        </header>
        <section className="count">
          <span className="num">{count}</span>
          <span className="lbl">people on this floor</span>
        </section>
        <section>
          <h2>View</h2>
          <div className="seg">
            {(["iso", "top"] as const).map((v) => (
              <button key={v} className={view === v ? "on" : ""} onClick={() => useUI.setState({ view: v })}>
                {v === "iso" ? "Angled" : "Top-down"}
              </button>
            ))}
          </div>
        </section>
        <section>
          <h2>Cameras</h2>
          <ul className="cams">
            {Object.values(cams).map((c) => (
              <li key={c.id}><i className={`dot ${c.state}`} />{c.name}<span>{c.state}{c.state === "online" && c.fps ? `, ${c.fps} fps` : ""}</span></li>
            ))}
          </ul>
        </section>
        <section className="alerts">
          <h2>Alerts</h2>
          {alerts.length === 0 && <p className="empty">No alerts yet. A person entering a red zone will appear here.</p>}
          <ul>
            {alerts.map((a) => (
              <li key={a.id} className={a.severity}>
                <b>{LABEL[a.type] ?? a.type}</b>
                <span>{a.zone}{a.tid != null ? `, person ${a.tid}` : ""} · {ago(a.ts)}</span>
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  );
}
