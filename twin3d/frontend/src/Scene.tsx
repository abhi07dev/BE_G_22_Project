import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { live, useUI } from "./store";

const MAX_PEOPLE = 4000;
const PERSON = new THREE.Color("#0b7a86");
const ALERT = new THREE.Color("#d6402b");
const CAM_COLOR: Record<string, string> = { online: "#2e8b57", offline: "#d6402b", unknown: "#8a98a3", degraded: "#c98a12" };

function People() {
  const ref = useRef<THREE.InstancedMesh>(null!);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame((_, dt) => {
    const mesh = ref.current;
    const now = performance.now() / 1000;
    const k = 1 - Math.exp(-dt * 12);
    let i = 0;
    for (const [id, p] of live.people) {
      if (now - p.seen > 1.5) { live.people.delete(id); continue; }
      if (i >= MAX_PEOPLE) break;
      p.x += (p.tx - p.x) * k;
      p.y += (p.ty - p.y) * k;
      dummy.position.set(p.x, 0.85, -p.y);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, p.red ? ALERT : PERSON);
      i++;
    }
    mesh.count = i;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, MAX_PEOPLE]} frustumCulled={false}>
      <cylinderGeometry args={[0.25, 0.25, 1.7, 8]} />
      <meshStandardMaterial />
    </instancedMesh>
  );
}

function Floor() {
  const { floor, zones, cams } = useUI();
  const W = floor.width_m, H = floor.height_m;
  const outline: [number, number, number][] = [[0, 0.02, 0], [W, 0.02, 0], [W, 0.02, -H], [0, 0.02, -H], [0, 0.02, 0]];
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[W / 2, 0, -H / 2]}>
        <planeGeometry args={[W, H]} />
        <meshStandardMaterial color="#f6f8f9" />
      </mesh>
      <gridHelper args={[Math.max(W, H), Math.max(W, H), "#c3ced6", "#dde4e9"]} position={[W / 2, 0.01, -H / 2]} />
      <Line points={outline} color="#13222e" lineWidth={2} />
      {zones.map((z) => {
        const shape = new THREE.Shape(z.polygon.map(([x, y]) => new THREE.Vector2(x, y)));
        const restricted = z.type === "restricted";
        return (
          <mesh key={z.id} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
            <shapeGeometry args={[shape]} />
            <meshBasicMaterial color={restricted ? "#d6402b" : "#0b7a86"} transparent opacity={restricted ? 0.28 : 0.14} />
          </mesh>
        );
      })}
      {Object.values(cams).map((c) => (
        <mesh key={c.id} position={[c.x, 3, -c.y]}>
          <coneGeometry args={[0.35, 0.7, 4]} />
          <meshStandardMaterial color={CAM_COLOR[c.state] ?? CAM_COLOR.unknown} />
        </mesh>
      ))}
    </>
  );
}

function CameraRig() {
  const { camera, controls } = useThree() as any;
  const view = useUI((s) => s.view);
  const { width_m: W, height_m: H } = useUI((s) => s.floor);
  useEffect(() => {
    const c = new THREE.Vector3(W / 2, 0, -H / 2);
    if (view === "top") camera.position.set(c.x, Math.max(W, H) * 1.1, c.z + 0.01);
    else camera.position.set(c.x + W * 0.55, Math.max(W, H) * 0.8, c.z + H * 1.1);
    controls?.target.copy(c);
    controls?.update();
  }, [view, W, H, camera, controls]);
  return null;
}

export default function Scene() {
  return (
    <Canvas camera={{ fov: 45, near: 0.1, far: 500 }} dpr={[1, 2]}>
      <color attach="background" args={["#e9eff2"]} />
      <hemisphereLight args={["#ffffff", "#9fb1bd", 1.1]} />
      <directionalLight position={[20, 40, 10]} intensity={0.8} />
      <Floor />
      <People />
      <OrbitControls makeDefault maxPolarAngle={Math.PI / 2.05} />
      <CameraRig />
    </Canvas>
  );
}
