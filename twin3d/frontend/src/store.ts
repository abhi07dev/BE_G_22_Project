import { create } from "zustand";

export type Zone = { id: number; name: string; type: string; polygon: [number, number][] };
export type Floor = { id: string; name: string; width_m: number; height_m: number };
export type Cam = { id: string; name: string; x: number; y: number; state: string; fps: number };
export type Alert = { id: number; type: string; zone: string; tid: number | null; ts: number; severity: string };
export type Person = { x: number; y: number; tx: number; ty: number; seen: number; red: boolean };

/** Mutable live state lives outside React: a 10 Hz stream must not re-render the tree. */
export const live = { people: new Map<number, Person>() };

type UI = {
  conn: "connecting" | "live" | "offline";
  count: number;
  floor: Floor;
  zones: Zone[];
  cams: Record<string, Cam>;
  alerts: Alert[];
  view: "iso" | "top";
};

export const useUI = create<UI>(() => ({
  conn: "connecting",
  count: 0,
  floor: { id: "F1", name: "Floor", width_m: 40, height_m: 25 },
  zones: [],
  cams: {},
  alerts: [],
  view: "iso",
}));
