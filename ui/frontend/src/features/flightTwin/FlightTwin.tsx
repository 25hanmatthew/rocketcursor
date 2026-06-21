// Flight Twin — the full rocket flying along its 6DOF trajectory from flight.csv.
// Position + attitude are driven by the shared timeline scrubber. RocketPy world
// (x downrange, y crossrange, z up) maps to three.js (x, z-up, -y). The rocket is
// drawn exaggerated (not to scale) so it stays visible against a km-scale arc.

import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Grid, Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { RocketMesh, RenderHints } from "../rocket/RocketMesh";
import { FlightRow, FlightEvents, interpolateFlight } from "../../lib/flightModel";

const UP = new THREE.Vector3(0, 1, 0);

function toWorld(x: number, y: number, z: number, scale: number): THREE.Vector3 {
  return new THREE.Vector3(x * scale, z * scale, -y * scale);
}

function eventLabel(t: number, events: FlightEvents): string {
  const order: Array<[keyof FlightEvents, string]> = [
    ["ignition", "Ignition"],
    ["rail_departure", "Rail clear"],
    ["maximum_dynamic_pressure", "Max-Q"],
    ["burnout", "Burnout"],
    ["apogee", "Apogee"],
    ["parachute_deployment", "Chute"],
    ["landing", "Landing"],
  ];
  let label = "Coast";
  for (const [key, name] of order) {
    const et = events[key];
    if (et != null && t >= et - 0.05) label = name;
  }
  return label;
}

export default function FlightTwin({
  rows,
  events,
  render,
  totalLength,
  time,
}: {
  rows: FlightRow[];
  events: FlightEvents;
  render: RenderHints;
  totalLength: number;
  time: number;
}) {
  const apogee = useMemo(() => Math.max(1, ...rows.map((r) => r.altitude - rows[0].altitude)), [rows]);
  const scale = 26 / apogee;
  const base = rows.length ? rows[0].altitude : 0;

  const sample = interpolateFlight(rows, time);
  const pos = sample ? toWorld(sample.position_x, sample.position_y, sample.altitude - base, scale) : new THREE.Vector3();

  // attitude: align rocket axis (+Y) to velocity; fall back to straight up on the pad
  const quat = useMemo(() => {
    const q = new THREE.Quaternion();
    if (!sample) return q;
    const v = toWorld(sample.velocity_x, sample.velocity_y, sample.velocity_z, 1);
    if (v.lengthSq() < 1e-4) return q;
    q.setFromUnitVectors(UP, v.normalize());
    return q;
  }, [sample]);

  const trail = useMemo(() => {
    const pts: [number, number, number][] = [];
    for (const r of rows) {
      if (r.time > time) break;
      const p = toWorld(r.position_x, r.position_y, r.altitude - base, scale);
      pts.push([p.x, p.y, p.z]);
    }
    return pts.length > 1 ? pts : null;
  }, [rows, time, base, scale]);

  const visScale = 2.6 / totalLength;
  const half = totalLength / 2;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <Canvas camera={{ position: [apogee * scale * 0.7, apogee * scale * 0.55, apogee * scale * 0.9], fov: 45 }}>
        <ambientLight intensity={0.8} />
        <hemisphereLight args={["#bcd4ff", "#0a0f18", 0.7]} />
        <directionalLight position={[20, 30, 10]} intensity={1.3} />
        <Grid position={[0, 0, 0]} args={[80, 80]} cellColor="#1f2937" sectionColor="#374151" infiniteGrid fadeDistance={90} />

        {trail && <Line points={trail} color="#38bdf8" lineWidth={2} />}

        <group position={pos} quaternion={quat}>
          <group scale={visScale}>
            <group position={[0, -half, 0]}>
              <RocketMesh render={render} />
            </group>
          </group>
        </group>

        <OrbitControls makeDefault enableDamping target={[pos.x, pos.y, pos.z]} />
      </Canvas>

      {sample && (
        <div className="flight-hud">
          <div className="flight-hud__phase">{eventLabel(time, events)}</div>
          <dl>
            <div><dt>Altitude</dt><dd>{(sample.altitude - base).toFixed(0)} m</dd></div>
            <div><dt>Velocity</dt><dd>{Math.hypot(sample.velocity_x, sample.velocity_y, sample.velocity_z).toFixed(0)} m/s</dd></div>
            <div><dt>Mach</dt><dd>{sample.mach.toFixed(2)}</dd></div>
            <div><dt>Dyn. pressure</dt><dd>{(sample.dynamic_pressure / 1000).toFixed(1)} kPa</dd></div>
            <div><dt>AoA</dt><dd>{sample.angle_of_attack.toFixed(1)}°</dd></div>
            <div><dt>Thrust</dt><dd>{(sample.thrust / 1000).toFixed(2)} kN</dd></div>
            <div><dt>Mass</dt><dd>{sample.mass.toFixed(1)} kg</dd></div>
          </dl>
        </div>
      )}
    </div>
  );
}
